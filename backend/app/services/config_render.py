# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fleet → Vector config renderer.

Compiles a fleet's designed topology (sources/sinks Components + Routes,
stored in Postgres) into a single valid Vector configuration document.

This is the *deploy unit*: a fleet's member instances all share one rendered
config. Local-mode instances get it written to their watched `config_dir`;
agent-mode instances get it POSTed to their agent.

Wiring mirrors `frontend/src/lib/fleetTopology.ts`: sources feed routes, routes
fan out to sinks per named branch plus the implicit `_unmatched` passthrough.
A Vector `route` transform named `r` exposes outputs `r.<branch>` and
`r._unmatched`, which sinks reference as `inputs`.

`config_json` is expected to hold already-typed values (arrays as lists, numbers
as numbers, booleans as bools) keyed by dot-notation field keys
(e.g. `multiline.mode`). Dotted keys are expanded into nested tables here.
"""

import json
import os
import pathlib
import re
from dataclasses import dataclass, field

import yaml

from app.core.config import settings
from app.models.component import Component
from app.models.route import Route
from app.services import secrets as secrets_svc

# Fixed config filename written into each local-mode instance's config_dir.
# Vector watches the directory via --watch-config and reloads on change.
CONFIG_FILENAME = "vector.yaml"


@dataclass
class RenderResult:
    yaml: str
    config: dict
    warnings: list[str] = field(default_factory=list)
    # Blocking problems (vs advisory `warnings`). A non-empty list means the
    # config is unsafe to deploy — e.g. two listeners bind the same host:port,
    # which renders fine but fails at Vector *reload* (runtime bind error that
    # `vector validate` does not catch). Deploy is gated on this being empty.
    errors: list[str] = field(default_factory=list)
    # resource id → rendered Vector component id (sanitized, collision-suffixed).
    # The single source of truth for tap targets and any other surface that
    # needs the deployed component name for a fleet resource.
    name_map: dict[str, str] = field(default_factory=dict)
    # Extra files this config needs on each host — TLS certs/keys pulled from the
    # cert store. Each is {path, content, mode}. Only populated when rendering
    # with reveal_secrets=True + cert_materials (deploy / agent). Local-mode
    # deploy writes them server-side; agent-mode delivers them in the pull.
    files: list[dict] = field(default_factory=list)


# Managed on-host directory for component TLS material. Same convention on every
# host so the rendered config path matches where the file is written (agent
# writes here as root; local-mode server writes here on the shared filesystem).
COMPONENT_CERTS_DIR = os.environ.get(
    "VORTEXFLOW_COMPONENT_CERTS_DIR", "/etc/vortexflow/component-certs"
)


# Hosts that bind every interface — a listener on one of these conflicts with
# *any* other listener on the same port/protocol (and vice-versa).
_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "*", "[::]"}


def _split_host_port(addr: str) -> tuple[str, str]:
    """Split a Vector listen `address` into (host, port). Handles bracketed
    IPv6 (`[::1]:514`), bare `:9000`, and `host:port`. Returns ("", "") when no
    port is present (e.g. a unix socket path)."""
    addr = addr.strip()
    if addr.startswith("["):  # [ipv6]:port
        host, _, rest = addr.partition("]")
        return host[1:], rest.lstrip(":")
    if ":" in addr:
        host, _, port = addr.rpartition(":")
        return host, port
    return addr, ""


def _bind_collisions(sources: dict[str, dict]) -> list[str]:
    """Detect listener bind collisions across a fleet's sources.

    Every fleet member shares one rendered config, so two listening sources on
    the same host:port (per transport) clash on every host. Vector accepts the
    config at validate time but fails at *reload* with a bind error. We catch it
    here, before deploy. ``sources`` is the rendered ``config["sources"]`` map
    (name → block); only blocks with a string ``address`` are listeners.
    """
    # name, original address, host, port, protocol
    listeners: list[tuple[str, str, str, str, str]] = []
    for name, block in sources.items():
        addr = block.get("address")
        if not isinstance(addr, str) or not addr.strip():
            continue
        host, port = _split_host_port(addr)
        if not port:  # unix socket path or non-listener; not a port collision
            continue
        mode = block.get("mode")
        proto = mode if mode in ("tcp", "udp") else "tcp"
        listeners.append((name, addr.strip(), host, port, proto))

    errors: list[str] = []
    seen: set[frozenset[str]] = set()
    for i in range(len(listeners)):
        n1, a1, h1, p1, pr1 = listeners[i]
        for j in range(i + 1, len(listeners)):
            n2, a2, h2, p2, pr2 = listeners[j]
            if p1 != p2 or pr1 != pr2:
                continue
            overlap = h1 == h2 or h1 in _WILDCARD_HOSTS or h2 in _WILDCARD_HOSTS
            if not overlap:
                continue
            pair = frozenset((n1, n2))
            if pair in seen:
                continue
            seen.add(pair)
            errors.append(
                f"sources '{n1}' ({a1}) and '{n2}' ({a2}) both bind {pr1} port "
                f"{p1} — duplicate listener address fails at Vector reload; "
                f"every fleet member shares this config."
            )
    return errors


def _safe_name(name: str) -> str:
    """Sanitize a user-facing name into a valid Vector component id."""
    cleaned = re.sub(r"[^a-z0-9_]", "_", name.strip().lower())
    return cleaned or "component"


def _expand_dot_keys(flat: dict) -> dict:
    """Expand {'a.b': 1, 'a.c': 2} into {'a': {'b': 1, 'c': 2}}."""
    out: dict = {}
    for key, value in flat.items():
        if value is None or value == "":
            continue
        parts = key.split(".")
        cursor = out
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = value
    return out


# Keys the renderer owns on every component block: ``type`` is the create-time
# allowlisted component type, ``inputs`` is the wiring the graph computes. A
# user-supplied ``config`` must never override them — letting ``config.type``
# through would defeat the type allowlist (a source could deploy as any sink
# type), and ``config.inputs`` would silently re-route the pipeline.
_RESERVED_BLOCK_KEYS = ("type", "inputs")


def _strip_reserved_keys(cfg: dict, label: str, warnings: list[str]) -> dict:
    for key in _RESERVED_BLOCK_KEYS:
        if key in cfg:
            cfg.pop(key)
            warnings.append(
                f"{label}: ignored reserved config key '{key}' "
                "(managed by the pipeline, not overridable)"
            )
    return cfg


def _load_config_json(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _component_config(
    c: Component,
    reveal_secrets: bool,
    cert_materials: dict | None,
    files: list[dict],
    warnings: list[str],
) -> dict:
    """A component's full flat config for rendering. Secret fields live encrypted
    in ``secrets_encrypted``; ``reveal_secrets=True`` (deploy) decrypts them,
    otherwise they render as the MASK sentinel (preview — never plaintext).

    Also resolves cert-store references: the ``tls.*_file`` paths are rewritten to
    the managed on-host location, and (when revealing) the referenced cert
    material is appended to ``files`` for delivery."""
    public = _load_config_json(c.config_json)
    enc = getattr(c, "secrets_encrypted", None)
    cfg = (
        secrets_svc.merge_revealed(public, enc, settings.at_rest_key)
        if reveal_secrets
        else secrets_svc.merge_masked(public, enc, settings.at_rest_key)
    )
    _apply_cert_refs(c, cfg, reveal_secrets, cert_materials, files, warnings)
    return cfg


def _apply_cert_refs(
    c: Component,
    cfg: dict,
    reveal_secrets: bool,
    cert_materials: dict | None,
    files: list[dict],
    warnings: list[str],
) -> None:
    """Wire a component's TLS fields to a stored cert. Rewrites the ``tls.*_file``
    keys to ``COMPONENT_CERTS_DIR/<component_id>/...`` and, when revealing with
    cert material available, emits the cert/key/ca files for on-host delivery."""
    refs = _load_config_json(getattr(c, "cert_refs_json", None) or "{}")
    identity = refs.get("identity")
    ca = refs.get("ca")
    if not identity and not ca:
        return
    base = f"{COMPONENT_CERTS_DIR}/{c.id}"
    if identity:
        cfg["tls.crt_file"] = f"{base}/crt.pem"
        cfg["tls.key_file"] = f"{base}/key.pem"
    if ca:
        cfg["tls.ca_file"] = f"{base}/ca.pem"
    if not reveal_secrets or cert_materials is None:
        return
    if identity:
        mat = cert_materials.get(identity)
        if mat:
            files.append(
                {"path": f"{base}/crt.pem", "content": mat["cert_pem"], "mode": 0o644}
            )
            if mat.get("key_pem"):
                files.append(
                    {
                        "path": f"{base}/key.pem",
                        "content": mat["key_pem"],
                        "mode": 0o600,
                    }
                )
            if mat.get("passphrase"):
                cfg["tls.key_pass"] = mat["passphrase"]
        else:
            warnings.append(f"{c.kind} '{c.name}': referenced certificate not found")
    if ca:
        mat = cert_materials.get(ca)
        if mat:
            content = mat.get("ca_chain_pem") or mat["cert_pem"]
            files.append({"path": f"{base}/ca.pem", "content": content, "mode": 0o644})
        else:
            warnings.append(f"{c.kind} '{c.name}': referenced CA certificate not found")


def render_fleet_config(
    components: list[Component],
    routes: list[Route],
    stages: list | None = None,
    library_vrl: dict[str, str] | None = None,
    reveal_secrets: bool = False,
    cert_materials: dict | None = None,
) -> RenderResult:
    """Render a fleet's components + routes (+ remap stages) into a Vector config.

    ``stages`` are remap nodes wired by ``inputs_json``; ``library_vrl`` maps a
    referenced vrl_transforms id to its current VRL (for mode='library' stages).

    ``reveal_secrets`` decrypts credential fields into the output — pass it only
    on the **deploy** path (writing the real config to a host or serving an
    agent). It defaults to ``False`` so previews and any incidental render are
    masked by default (fail-safe).

    ``cert_materials`` maps a cert-store id to its decrypted material
    (``{cert_pem, key_pem?, ca_chain_pem?, passphrase?}``); supplied by the
    deploy/agent caller so component TLS refs render to managed paths and the cert
    files land in ``RenderResult.files``. Render itself stays DB-free.
    """
    warnings: list[str] = []
    files: list[dict] = []
    stages = stages or []
    library_vrl = library_vrl or {}

    sources = [c for c in components if c.kind == "source"]
    sinks = [c for c in components if c.kind == "sink"]
    sink_by_id = {s.id: s for s in sinks}
    source_by_id = {s.id: s for s in sources}
    stage_by_id = {s.id: s for s in stages}

    # Resolve every component/route to a unique, sanitized Vector id.
    name_map: dict[str, str] = {}
    used: dict[str, str] = {}  # safe_name -> originating resource id

    def assign(resource_id: str, raw_name: str, kind: str) -> str:
        base = _safe_name(raw_name)
        candidate = base
        n = 2
        while candidate in used and used[candidate] != resource_id:
            candidate = f"{base}_{n}"
            n += 1
        if candidate != base and used.get(base) != resource_id:
            warnings.append(
                f"{kind} name '{raw_name}' collided; renamed to '{candidate}'"
            )
        used[candidate] = resource_id
        name_map[resource_id] = candidate
        return candidate

    for c in components:
        assign(c.id, c.name, c.kind)
    for st in stages:
        assign(st.id, st.name, "transform")
    for r in routes:
        assign(r.id, r.name, "route")

    config: dict = {"sources": {}, "transforms": {}, "sinks": {}}
    wired: set[str] = set()

    # Track input lists per sink id (a sink can be fed by several branches).
    sink_inputs: dict[str, list[str]] = {s.id: [] for s in sinks}

    # Sources
    for c in sources:
        block: dict = {"type": c.component_type}
        block.update(
            _strip_reserved_keys(
                _expand_dot_keys(
                    _component_config(
                        c, reveal_secrets, cert_materials, files, warnings
                    )
                ),
                f"{c.kind} '{c.name}'",
                warnings,
            )
        )
        config["sources"][name_map[c.id]] = block

    # Remap stages: source → remap → route. Inputs reference sources or other
    # stages; VRL is inline or resolved from the referenced library template.
    for st in stages:
        sname = name_map[st.id]
        stage_inputs: list[str] = []
        for iid in _json_list(st.inputs_json):
            if iid in source_by_id or iid in stage_by_id:
                wired.add(iid)
                stage_inputs.append(name_map[iid])
        vrl = (
            st.source_vrl
            if st.mode == "inline"
            else library_vrl.get(st.transform_id or "", "")
        )
        if not stage_inputs:
            warnings.append(f"remap '{st.name}' has no wired inputs; skipped")
            continue
        if not (vrl and vrl.strip()):
            warnings.append(f"remap '{st.name}' has no VRL; skipped")
            continue
        config["transforms"][sname] = {
            "type": "remap",
            "inputs": stage_inputs,
            "source": vrl,
        }

    # Route transforms
    for r in routes:
        rname = name_map[r.id]
        inputs = []
        for sid in _json_list(r.source_ids_json):
            if sid in source_by_id or sid in stage_by_id:
                wired.add(sid)
                inputs.append(name_map[sid])
        branches = _json_list(r.branches_json)
        route_table: dict[str, str] = {}
        for b in branches:
            if not isinstance(b, dict):
                continue
            bname = _safe_name(str(b.get("name", "")))
            cond = b.get("condition", "")
            if not bname or not cond:
                continue
            route_table[bname] = cond
            for sink_id in b.get("sink_ids", []):
                if sink_id in sink_by_id:
                    wired.add(sink_id)
                    sink_inputs[sink_id].append(f"{rname}.{bname}")
        for sink_id in _json_list(r.passthrough_sink_ids_json):
            if sink_id in sink_by_id:
                wired.add(sink_id)
                sink_inputs[sink_id].append(f"{rname}._unmatched")

        if not inputs:
            warnings.append(f"route '{r.name}' has no wired sources; skipped")
            continue
        if not route_table:
            warnings.append(f"route '{r.name}' has no valid branches; skipped")
            continue
        config["transforms"][rname] = {
            "type": "route",
            "inputs": inputs,
            "route": route_table,
        }

    # Sinks. A sink's inputs are the union of route-branch outputs that target it
    # and its own direct inputs (sources/stages) — the latter enables wiring a
    # destination without a route (quick-connect / fan-out).
    for c in sinks:
        block = {"type": c.component_type}
        ins = list(sink_inputs.get(c.id, []))
        for iid in _json_list(c.inputs_json):
            if iid in source_by_id or iid in stage_by_id:
                wired.add(iid)  # upstream is consumed
                wired.add(c.id)  # sink is connected (terminal, but wired up)
                nm = name_map[iid]
                if nm not in ins:
                    ins.append(nm)
        if ins:
            block["inputs"] = ins
        block.update(
            _strip_reserved_keys(
                _expand_dot_keys(
                    _component_config(
                        c, reveal_secrets, cert_materials, files, warnings
                    )
                ),
                f"{c.kind} '{c.name}'",
                warnings,
            )
        )
        config["sinks"][name_map[c.id]] = block

    # Orphan warnings
    for c in components:
        if c.id not in wired:
            warnings.append(f"{c.kind} '{c.name}' is not wired to anything")
    for st in stages:
        if st.id not in wired:
            warnings.append(f"remap '{st.name}' is not consumed by anything")

    # Blocking checks (unsafe to deploy) — distinct from advisory warnings.
    errors = _bind_collisions(config["sources"])

    # Drop empty top-level tables for a cleaner document.
    config = {k: v for k, v in config.items() if v}

    rendered = yaml.safe_dump(config, sort_keys=False, default_flow_style=False)
    return RenderResult(
        yaml=rendered,
        config=config,
        warnings=warnings,
        errors=errors,
        name_map=name_map,
        files=files,
    )


def serialize_with_globals(
    base_config: dict,
    *,
    data_dir: str | None = None,
    expire_metrics_secs: int | None = None,
) -> str:
    """Serialize a rendered fleet config with per-instance Vector global options
    merged in at the top level. The fleet config is shared across members; these
    globals (where Vector stores buffers/state, metric cardinality bound) vary per
    host and are applied at deploy time."""
    globals_block: dict = {}
    if data_dir:
        globals_block["data_dir"] = data_dir
    if expire_metrics_secs is not None:
        globals_block["expire_metrics_secs"] = expire_metrics_secs
    merged = {**globals_block, **base_config}
    return yaml.safe_dump(merged, sort_keys=False, default_flow_style=False)


@dataclass
class ValidateResult:
    # "valid"       — `vector validate` exited 0
    # "invalid"     — `vector validate` rejected the config (output explains why)
    # "unavailable" — no vector binary / couldn't run validate (non-blocking)
    status: str
    output: str = ""


def collect_secret_values(config: dict) -> set[str]:
    """Plaintext secret values in a *revealed* render, for scrubbing from
    ``vector validate`` output before it is shown to an editor.

    Walks the rendered config tree and collects EVERY non-empty leaf value whose
    key names a credential (per ``is_secret_key``). No length floor: a short real
    secret (a 3-char token, a numeric PIN) must still be redacted from validator
    output — better to over-redact an incidental match than leak a credential.
    """
    found: set[str] = set()

    def walk(node: object, key: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)
        elif (
            key
            and secrets_svc.is_secret_key(key)
            and node
            not in (
                None,
                "",
                secrets_svc.MASK,
            )
        ):
            found.add(str(node))

    walk(config, "")
    return found


def validate_config(
    content: str, *, redact: set[str] | None = None, timeout: float = 20.0
) -> ValidateResult:
    """Run `vector validate` against rendered config text, server-side.

    Writes the config to a private temp file and shells out via an arg list (no
    shell, no user-controlled args beyond our own temp path). Vector is bundled
    in the backend image; where it's absent (dev boxes, TLS-terminated installs)
    this returns ``unavailable`` so callers can degrade gracefully instead of
    blocking every deploy. The temp path is scrubbed from the returned output;
    when validating a revealed (secrets-inlined) config, pass ``redact`` (see
    ``collect_secret_values``) so a validator error echoing a value can't leak
    the plaintext secret back to the caller.
    """
    import shutil
    import subprocess
    import tempfile

    from app.core.config import settings

    vector_bin = settings.vector_bin or "vector"
    # Resolve to a concrete executable; if it isn't on PATH / doesn't exist,
    # validation is simply unavailable here (don't block deploys on it).
    resolved = shutil.which(vector_bin) or (
        vector_bin if os.path.isabs(vector_bin) and os.path.exists(vector_bin) else None
    )
    if not resolved:
        return ValidateResult(status="unavailable", output="vector binary not found")

    tmp_dir = tempfile.mkdtemp(prefix="vf-validate-")
    tmp_path = os.path.join(tmp_dir, CONFIG_FILENAME)
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        try:
            proc = subprocess.run(
                [resolved, "validate", tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ValidateResult(
                status="unavailable", output="vector validate timed out"
            )
        except OSError:
            return ValidateResult(
                status="unavailable", output="could not run vector validate"
            )
        # Scrub the temp path so callers never see server filesystem internals.
        raw = ((proc.stdout or "") + (proc.stderr or "")).strip()
        cleaned = raw.replace(tmp_path, CONFIG_FILENAME).replace(tmp_dir, "")
        # Scrub any inlined secret values a validator error may have echoed back.
        for val in redact or ():
            if val:
                cleaned = cleaned.replace(val, "«redacted-secret»")
        if proc.returncode == 0:
            return ValidateResult(status="valid", output=cleaned)
        return ValidateResult(status="invalid", output=cleaned)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def write_local_config(config_dir: str, content: str) -> str:
    """Atomically write rendered config to `<config_dir>/vector.yaml`.

    Hardened against symlink swaps (O_NOFOLLOW on the temp file) and requires an
    absolute directory. Returns the path written. The filename is fixed — no
    user input reaches the path component beyond the admin-set directory.
    """
    if not config_dir or not os.path.isabs(config_dir):
        raise ValueError("config_dir must be a non-empty absolute path")
    directory = pathlib.Path(config_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / CONFIG_FILENAME
    tmp = str(dest) + ".tmp"
    # 0o600, not 0o644: the rendered config can contain DECRYPTED secrets on the
    # deploy path (sink credentials, TLS key passphrases), so it must not be
    # world-readable. Vector reads it as the owning user (agent/local-write both
    # run the writer and reader as the same account or root).
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    os.rename(tmp, str(dest))
    return str(dest)


def _json_list(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
