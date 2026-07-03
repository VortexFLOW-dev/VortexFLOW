# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Serves the Vector agent bootstrap install script.
GET /install/fleet/{fleet_id}?token=<bootstrap_token>&host=<vortexflow_url>

Returns a bash script that:
  1. Installs Vector via the official install script
  2. Writes a minimal Vector config pointing back to VortexFlow's VM remote_write
  3. Calls VortexFlow's bootstrap API to register and receive the full pipeline config
"""

import hashlib
import hmac
import logging
import os
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.fleet import Fleet
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter()

# Bootstrap tokens are urlsafe base64 — only alphanumeric, dash, underscore
_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_]{20,64}$")

# Allowlists for the agent binary download — these become a filename, so they
# must be strictly constrained (no path traversal).
_ALLOWED_GOOS = {"linux", "darwin"}
_ALLOWED_GOARCH = {"amd64", "arm64"}


@router.get("/agent/{goos}/{goarch}")
async def download_agent(goos: str, goarch: str) -> FileResponse:
    """Serve the prebuilt vortexflow-agent binary for a platform. The install
    script downloads this onto the Vector host."""
    if goos not in _ALLOWED_GOOS or goarch not in _ALLOWED_GOARCH:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown platform"
        )
    # Filename is built only from allowlisted constants — no user-controlled path.
    name = f"vortexflow-agent-{goos}-{goarch}"
    path = os.path.join(settings.agent_bin_dir, name)
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent binary not available for this platform",
        )
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.get("/ca.crt")
async def download_ca() -> FileResponse:
    """Serve the CA certificate so agents can trust this server's (self-signed)
    TLS without disabling verification. 404 if TLS isn't self-managed here."""
    if not settings.tls_cert_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No managed CA"
        )
    path = os.path.join(settings.tls_cert_dir, "ca.pem")
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="CA not available"
        )
    return FileResponse(
        path, media_type="application/x-pem-file", filename="vortexflow-ca.crt"
    )


def _safe_shell_value(value: str) -> str:
    """Return value wrapped in single quotes, escaping any embedded single quotes."""
    return "'" + value.replace("'", "'\\''") + "'"


def _validate_host(host: str) -> str:
    """Validate host is a well-formed http/https URL. Raises HTTPException otherwise."""
    # Reject whitespace/control chars up front: `host` is interpolated raw into
    # the generated install script (including a YAML heredoc), so a newline could
    # otherwise break out of the heredoc into the root-run script.
    if any(c.isspace() or ord(c) < 0x20 for c in host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid host URL"
        )
    try:
        parsed = urlparse(host)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid host URL"
        )
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="host must be http or https"
        )
    if not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="host must include a hostname",
        )
    # Strip trailing slash
    return host.rstrip("/")


@router.get("/fleet/{fleet_id}", response_class=PlainTextResponse)
async def install_script(
    request: Request,
    fleet_id: str,
    # Token in a header, not the URL query — a query string lands in nginx/proxy
    # access logs and any intermediary; a request header does not.
    x_bootstrap_token: str = Header(..., alias="X-Bootstrap-Token"),
    host: str | None = Query(
        None, description="VortexFlow base URL (auto-detected from request if omitted)"
    ),
) -> PlainTextResponse:
    # Validate token format before hitting the DB (fast reject)
    if not _TOKEN_RE.match(x_bootstrap_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bootstrap token"
        )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Fleet).where(Fleet.id == fleet_id))
        fleet = result.scalar_one_or_none()

    if not fleet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found"
        )

    # Require a bootstrap token to be configured — never serve the script to unauthenticated callers
    if not fleet.bootstrap_token_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bootstrap token not configured for this fleet. Generate one first.",
        )

    # Constant-time comparison to prevent timing attacks
    candidate_hash = hashlib.sha256(x_bootstrap_token.encode()).hexdigest()
    if not hmac.compare_digest(candidate_hash, fleet.bootstrap_token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bootstrap token"
        )

    # Determine the VortexFlow base URL that gets baked into a ROOT-run install
    # script. A configured public_url is authoritative and always wins — a
    # request-supplied `host` param or `Host` header must NOT be able to point
    # the script (and therefore the agent's CA/binary/config fetch) at an
    # attacker's server. Only in debug (dev) do we fall back to a request-derived
    # host for convenience.
    from app.core.config import settings as app_settings

    if app_settings.public_url:
        host = _validate_host(app_settings.public_url.rstrip("/"))
    elif app_settings.debug:
        inferred = host or str(request.base_url).rstrip("/")
        host = _validate_host(inferred)
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Server public_url is not configured. Set VORTEXFLOW_PUBLIC_URL "
                "so the install script points agents at the correct address."
            ),
        )

    # Shell-safe values for embedding in the script
    safe_fleet_id = _safe_shell_value(fleet_id)
    safe_token = _safe_shell_value(x_bootstrap_token)
    safe_host = _safe_shell_value(host)
    safe_vm_url = _safe_shell_value(f"{host}/vm")
    safe_fleet_name = _safe_shell_value(fleet.name)

    # sha256 of the agent binaries this server will serve, per arch. Embedded in
    # the script so the download can be verified against a value the operator got
    # over their authenticated admin session — not the agent host's download
    # channel (whose TLS root may be trust-on-first-use). Closes the "no integrity
    # check independent of TLS" gap. Empty if a binary isn't present server-side.
    from app.core.config import settings as _bin_settings

    def _agent_sha(goarch: str) -> str:
        try:
            with open(
                os.path.join(
                    _bin_settings.agent_bin_dir, f"vortexflow-agent-linux-{goarch}"
                ),
                "rb",
            ) as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return ""

    sha_amd64 = _agent_sha("amd64")
    sha_arm64 = _agent_sha("arm64")

    # The vm_url is also embedded inside the VECTOREOF heredoc (YAML value, not shell)
    # Use the raw string only — we've already validated host is a proper URL
    vm_endpoint = f"{host}/vm/api/v1/write"

    script = f"""\
#!/usr/bin/env bash
# VortexFlow agent bootstrap
# Generated by VortexFlow. Do not edit manually.
set -euo pipefail

FLEET_ID={safe_fleet_id}
BOOTSTRAP_TOKEN={safe_token}
VORTEXFLOW_URL={safe_host}
VM_URL={safe_vm_url}
VECTOR_CONFIG_DIR="/etc/vector"
# Static metrics config (install-managed). The agent owns vortexflow.yaml in the
# same dir — Vector loads the whole dir via --config-dir and merges them.
METRICS_FILE="${{VECTOR_CONFIG_DIR}}/00-vortexflow-metrics.yaml"
AGENT_CONFIG_FILE="${{VECTOR_CONFIG_DIR}}/vortexflow.yaml"
AGENT_BIN="/usr/local/bin/vortexflow-agent"
AGENT_ENV="/etc/vortexflow/agent.env"

# ── Require root ──────────────────────────────────────────────────────────────
if [ "${{EUID:-$(id -u)}}" -ne 0 ]; then
  echo "ERROR: Run this script as root (sudo bash)." >&2
  exit 1
fi

# ── Install Vector ────────────────────────────────────────────────────────────
if ! command -v vector &>/dev/null; then
  echo "→ Installing Vector..."
  curl -1sLf 'https://setup.vector.dev' | bash
  apt-get install -y vector 2>/dev/null || \\
    yum install -y vector 2>/dev/null || \\
    dnf install -y vector 2>/dev/null || \\
    {{ echo "ERROR: Could not install Vector. Install it manually then re-run."; exit 1; }}
else
  echo "→ Vector already installed: $(vector --version)"
fi

# ── Trust the leader's CA (self-signed TLS) ───────────────────────────────────
# Fetch the CA over -k (trust-on-first-use), then verify everything else with it.
# A 404 means TLS isn't self-managed here (plain HTTP or a real cert) — carry on.
mkdir -p /etc/vortexflow
CA_FILE=""
CURL_CA=""
if curl -fsSLk "${{VORTEXFLOW_URL}}/install/ca.crt" -o /etc/vortexflow/ca.crt 2>/dev/null && [ -s /etc/vortexflow/ca.crt ]; then
  CA_FILE=/etc/vortexflow/ca.crt
  CURL_CA="--cacert ${{CA_FILE}}"
  echo "→ Installed VortexFlow CA for TLS verification."
else
  rm -f /etc/vortexflow/ca.crt
fi

# ── Write static metrics config ───────────────────────────────────────────────
# Ships Vector's own internal metrics back to VortexFlow so the host shows up on
# the health dashboard. Separate from the agent-managed pipeline config.
echo "→ Writing metrics config to ${{METRICS_FILE}}..."
mkdir -p "${{VECTOR_CONFIG_DIR}}"
# Remove the distro's example config so only VortexFlow-managed files run.
rm -f "${{VECTOR_CONFIG_DIR}}/vector.yaml" "${{VECTOR_CONFIG_DIR}}/vector.toml"
cat > "${{METRICS_FILE}}" <<'VECTOREOF'
# Managed by VortexFlow — do not edit manually.
sources:
  internal_metrics:
    type: internal_metrics
sinks:
  vortexflow_metrics:
    type: prometheus_remote_write
    inputs: [internal_metrics]
    endpoint: "{vm_endpoint}"
VECTOREOF
# Trust the leader's CA for the metrics remote-write when TLS is self-managed.
if [ -n "${{CA_FILE}}" ]; then
  cat >> "${{METRICS_FILE}}" <<EOF
    tls:
      ca_file: ${{CA_FILE}}
EOF
fi

# ── Register with VortexFlow ──────────────────────────────────────────────────
echo "→ Registering with VortexFlow..."
HOSTNAME=$(hostname)
HOST_IP=$(hostname -I 2>/dev/null | awk '{{print $1}}' || echo "127.0.0.1")
REGISTER_RESPONSE=$(curl -sf ${{CURL_CA}} \\
  -X POST "${{VORTEXFLOW_URL}}/api/v1/fleets/${{FLEET_ID}}/register" \\
  -H "Content-Type: application/json" \\
  -H "X-Bootstrap-Token: ${{BOOTSTRAP_TOKEN}}" \\
  -d "{{\\"hostname\\": \\"${{HOSTNAME}}\\", \\"api_url\\": \\"http://${{HOST_IP}}:8686\\"}}" \\
  2>/dev/null) || true

INSTANCE_ID=$(printf '%s' "${{REGISTER_RESPONSE}}" \\
  | grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\\1/')
AGENT_TOKEN=$(printf '%s' "${{REGISTER_RESPONSE}}" \\
  | grep -oE '"agent_token"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\\1/')

if [ -z "${{INSTANCE_ID}}" ] || [ -z "${{AGENT_TOKEN}}" ]; then
  echo "ERROR: Registration failed — could not obtain an agent token." >&2
  echo "  Response: ${{REGISTER_RESPONSE}}" >&2
  exit 1
fi
echo "→ Registered as instance ${{INSTANCE_ID}}."

# ── Install the VortexFlow agent ──────────────────────────────────────────────
ARCH=$(uname -m)
case "${{ARCH}}" in
  x86_64|amd64) GOARCH=amd64 ;;
  aarch64|arm64) GOARCH=arm64 ;;
  *) echo "ERROR: unsupported architecture ${{ARCH}}" >&2; exit 1 ;;
esac
echo "→ Downloading agent (linux/${{GOARCH}})..."
curl -fsSL ${{CURL_CA}} "${{VORTEXFLOW_URL}}/install/agent/linux/${{GOARCH}}" -o "${{AGENT_BIN}}"
# Verify the download against the checksum embedded in this script (delivered via
# the operator's authenticated session, not this host's download channel), so a
# tampered binary is rejected even if the download's TLS root is trust-on-first-use.
case "${{GOARCH}}" in
  amd64) EXPECTED_SHA="{sha_amd64}" ;;
  arm64) EXPECTED_SHA="{sha_arm64}" ;;
  *) EXPECTED_SHA="" ;;
esac
if [ -n "$EXPECTED_SHA" ]; then
  ACTUAL_SHA=$(sha256sum "${{AGENT_BIN}}" | awk '{{print $1}}')
  if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    echo "ERROR: agent binary checksum mismatch — refusing to install." >&2
    rm -f "${{AGENT_BIN}}"; exit 1
  fi
  echo "→ Agent binary checksum verified."
else
  echo "WARNING: no checksum available for linux/${{GOARCH}}; skipping verification." >&2
fi
chmod 0755 "${{AGENT_BIN}}"

# Agent credentials — root-owned, 0600 (holds the agent token). AGENT_CA_CERT is
# empty when TLS isn't self-managed, which the agent treats as "use system roots".
echo "→ Writing agent environment to ${{AGENT_ENV}}..."
( umask 077; cat > "${{AGENT_ENV}}" <<EOF
VORTEXFLOW_URL=${{VORTEXFLOW_URL}}
INSTANCE_ID=${{INSTANCE_ID}}
AGENT_TOKEN=${{AGENT_TOKEN}}
VECTOR_CONFIG_PATH=${{AGENT_CONFIG_FILE}}
AGENT_CA_CERT=${{CA_FILE}}
EOF
)
chmod 0600 "${{AGENT_ENV}}"

echo "→ Installing systemd unit..."
cat > /etc/systemd/system/vortexflow-agent.service <<'EOF'
[Unit]
Description=VortexFlow agent — keeps Vector config converged
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/vortexflow/agent.env
ExecStart=/usr/local/bin/vortexflow-agent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── Enable and start services ─────────────────────────────────────────────────
echo "→ Enabling Vector and the agent..."
systemctl daemon-reload
systemctl enable vector
systemctl restart vector
systemctl enable --now vortexflow-agent

echo ""
echo "✓ VortexFlow agent installed and registered to fleet: {safe_fleet_name}"
echo "  Instance: ${{INSTANCE_ID}}"
echo "  Metrics:  ${{VM_URL}}"
echo "  Control:  ${{VORTEXFLOW_URL}}"
echo "  The agent will pull and apply the fleet config within a poll interval."
"""

    return PlainTextResponse(content=script, media_type="text/x-shellscript")
