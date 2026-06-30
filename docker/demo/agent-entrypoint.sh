#!/usr/bin/env bash
# Demo agent — the full end-to-end loop with REAL Vector moving REAL data.
#
# Parameterized so you can run several of these to populate multiple fleets and
# see the stacked throughput-by-fleet hero:
#   FLEET_NAME      fleet to join (created if missing); default "Default"
#   HOSTNAME_TAG    this agent's hostname / api_url host / metrics host tag;
#                   default "demo-agent". MUST match the container --name so the
#                   backend health probe can reach http://<tag>:8686.
#   DEMO_INTERVAL   demo_logs emit interval in seconds (lower = more events/s),
#                   so different fleets get different throughput; default 1.0
#
# On start it: registers to the fleet, seeds a demo_logs → remap → console
# pipeline, deploys it, then runs Vector (static self-monitoring config —
# internal_metrics tagged host=<HOSTNAME_TAG> → VM — merged with the
# agent-managed fleet config via --watch-config) plus the vortexflow-agent.
# Demo only — talks to the backend over plain internal HTTP.
set -euo pipefail

API="${VORTEXFLOW_API:-http://backend:8000}"
EMAIL="${ADMIN_EMAIL:-admin@example.com}"
PASS="${ADMIN_PASSWORD:-ChangeMe123!}"
FLEET_NAME="${FLEET_NAME:-Default}"
HOSTNAME_TAG="${HOSTNAME_TAG:-demo-agent}"
DEMO_INTERVAL="${DEMO_INTERVAL:-1.0}"
# SEED_DEMO=false attaches the agent to a pre-built fleet without seeding the
# sample demo_logs pipeline (and without auto-deploying) — useful when the
# fleet's pipeline is authored elsewhere (e.g. in the UI).
SEED_DEMO="${SEED_DEMO:-true}"
STATIC_CONFIG="/etc/vector/demo-metrics.yaml"
FLEET_CONFIG="/tmp/vortexflow.yaml"

echo "demo-agent[${HOSTNAME_TAG}]: waiting for backend at ${API}..."
until curl -fsS "${API}/api/v1/health" >/dev/null 2>&1; do sleep 2; done

# Extract the first JSON string value for a key (good enough for our responses).
extract() { grep -o "\"$1\":\"[^\"]*\"" | head -1 | cut -d'"' -f4; }

TOK=$(curl -fsS -X POST "${API}/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASS}\"}" | extract access_token)
AUTH="Authorization: Bearer ${TOK}"
JSON='Content-Type: application/json'

# ── Find the target fleet by name (split objects onto lines, grep the name,
# pull its id); create it if missing. ────────────────────────────────────────
# `|| true`: grep exits 1 when the fleet doesn't exist yet, which under
# `set -o pipefail` would otherwise kill the script before the create branch.
FID=$(curl -fsS "${API}/api/v1/fleets" -H "${AUTH}" | tr '}' '\n' \
  | grep "\"name\":\"${FLEET_NAME}\"" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
if [ -z "${FID}" ]; then
  echo "demo-agent[${HOSTNAME_TAG}]: creating fleet '${FLEET_NAME}'"
  FID=$(curl -fsS -X POST "${API}/api/v1/fleets" -H "${AUTH}" -H "${JSON}" \
    -d "{\"name\":\"${FLEET_NAME}\"}" | extract id)
fi
echo "demo-agent[${HOSTNAME_TAG}]: fleet '${FLEET_NAME}' = ${FID}"

# ── 1. Register this host as an agent in the fleet ────────────────────────────
BT=$(curl -fsS -X POST "${API}/api/v1/fleets/${FID}/bootstrap-token" -H "${AUTH}" | extract token)
REG=$(curl -fsS -X POST "${API}/api/v1/fleets/${FID}/register" \
  -H "X-Bootstrap-Token: ${BT}" -H "${JSON}" \
  -d "{\"hostname\":\"${HOSTNAME_TAG}\",\"api_url\":\"http://${HOSTNAME_TAG}:8686\"}")
IID=$(printf '%s' "${REG}" | extract id)
ATOK=$(printf '%s' "${REG}" | extract agent_token)
if [ -z "${IID}" ] || [ -z "${ATOK}" ]; then
  echo "demo-agent[${HOSTNAME_TAG}]: registration failed: ${REG}" >&2
  exit 1
fi
echo "demo-agent[${HOSTNAME_TAG}]: registered as ${IID}"

# ── 2. Seed a sample pipeline (idempotent: skip if the source already exists) ──
EXISTING=$(curl -fsS "${API}/api/v1/components?fleet_id=${FID}&kind=source" -H "${AUTH}")
if [ "${SEED_DEMO}" != "true" ]; then
  echo "demo-agent[${HOSTNAME_TAG}]: SEED_DEMO=${SEED_DEMO}; attaching to pre-built fleet (no seed/deploy)"
elif printf '%s' "${EXISTING}" | grep -q '"name":"Demo Logs"'; then
  echo "demo-agent[${HOSTNAME_TAG}]: sample pipeline already present; skipping seed"
else
  echo "demo-agent[${HOSTNAME_TAG}]: seeding demo_logs → remap → console (interval=${DEMO_INTERVAL})"
  SRC=$(curl -fsS -X POST "${API}/api/v1/components" -H "${AUTH}" -H "${JSON}" -d "{
      \"fleet_id\":\"${FID}\",\"kind\":\"source\",\"name\":\"Demo Logs\",
      \"component_type\":\"demo_logs\",
      \"config\":{\"format\":\"json\",\"interval\":${DEMO_INTERVAL}}
    }" | extract id)
  STAGE=$(curl -fsS -X POST "${API}/api/v1/transform-stages" -H "${AUTH}" -H "${JSON}" -d "{
      \"fleet_id\":\"${FID}\",\"name\":\"Tag\",\"mode\":\"inline\",
      \"source_vrl\":\".source = \\\"${HOSTNAME_TAG}\\\"\",
      \"inputs\":[\"${SRC}\"]
    }" | extract id)
  curl -fsS -X POST "${API}/api/v1/components" -H "${AUTH}" -H "${JSON}" -d "{
      \"fleet_id\":\"${FID}\",\"kind\":\"sink\",\"name\":\"Console\",
      \"component_type\":\"console\",
      \"config\":{\"encoding.codec\":\"json\"},
      \"inputs\":[\"${STAGE}\"]
    }" >/dev/null
  echo "demo-agent[${HOSTNAME_TAG}]: seeded (source=${SRC} stage=${STAGE})"
fi

# ── 3. Publish it (bumps the fleet generation the agent converges to) ─────────
# Only when we seeded — a pre-built fleet is deployed by whoever authored it.
if [ "${SEED_DEMO}" = "true" ]; then
  curl -fsS -X POST "${API}/api/v1/fleets/${FID}/deploy" -H "${AUTH}" >/dev/null || \
    echo "demo-agent[${HOSTNAME_TAG}]: deploy returned non-zero (may be gated); continuing"
fi

# ── 4. Start REAL Vector: static self-monitoring + agent-managed fleet config ──
# Pre-create the agent-managed file so --watch-config has it from the start; the
# agent overwrites it on first successful pull. VF_HOST_TAG drives the metrics
# host tag in demo-metrics.yaml so each agent's throughput maps to its fleet.
mkdir -p "$(dirname "${FLEET_CONFIG}")" /var/lib/vector
printf '# managed by vortexflow-agent\n' > "${FLEET_CONFIG}"
export VF_HOST_TAG="${HOSTNAME_TAG}"

# ── Optional fault injection (demo of unhealthy states) ───────────────────────
# INJECT_FAULTS=true adds a self-contained pipeline that ships to an always-503
# endpoint (FAULT_SINK_URL) through a small drop-when-full buffer. It runs in the
# SAME Vector process, so internal_metrics (tagged host=<HOSTNAME_TAG>) exposes
# the red signals the instance-health panels surface: vector_component_errors_total,
# vector_http_client_responses_total{status="503"}, vector_buffer_events filling,
# and vector_component_discarded_events_total climbing (data loss). Demo only.
FAULT_CONFIG="/etc/vector/fault.yaml"
FAULT_ARGS=()
if [ "${INJECT_FAULTS:-false}" = "true" ]; then
  echo "demo-agent[${HOSTNAME_TAG}]: INJECT_FAULTS=true → adding flaky sink"
  cat > "${FAULT_CONFIG}" <<EOF
# Two independent generators so the blocking black-hole sink can't back-pressure
# (and silence) the 503 path — each fault sustains its own red signal.
sources:
  fault_gen_503:
    type: demo_logs
    format: json
    interval: ${FAULT_INTERVAL:-0.2}
  fault_gen_drop:
    type: demo_logs
    format: json
    interval: ${FAULT_DROP_INTERVAL:-0.02}
  fault_gen_block:
    type: demo_logs
    format: json
    interval: ${FAULT_BLOCK_INTERVAL:-0.1}
sinks:
  # Always-503 endpoint with retries OFF → it fails fast instead of throttling,
  # so vector_http_client_responses_total{status="503"} stays high (sustained
  # "sink delivery failing" signal). Errors also accrue here.
  fault_503:
    type: http
    inputs: [fault_gen_503]
    uri: ${FAULT_SINK_URL:-http://fault-sink:8080/}
    encoding:
      codec: json
    request:
      retry_attempts: 0
    healthcheck:
      enabled: false
  # Black-hole (unroutable IP) → requests hang on connect; the small drop-newest
  # buffer fills (vector_buffer_events ≈ max, sustained backpressure) and
  # overflows (vector_component_discarded_events_total climbs — data loss).
  fault_blackhole:
    type: http
    inputs: [fault_gen_drop]
    uri: http://10.255.255.1:8080/
    encoding:
      codec: json
    buffer:
      type: memory
      max_events: 500
      when_full: drop_newest
    request:
      timeout_secs: 2
      retry_attempts: 1
    healthcheck:
      enabled: false
  # Backpressure signal: the 503 endpoint (which DOES respond) with retries ON,
  # so each event re-sends repeatedly → the sink drains far slower than the source
  # fills it → the block buffer pegs full and STAYS full (sustained
  # vector_buffer_events ≈ max), the clearest backpressure signal.
  fault_backpressure:
    type: http
    inputs: [fault_gen_block]
    uri: ${FAULT_SINK_URL:-http://fault-sink:8080/}
    encoding:
      codec: json
    buffer:
      type: memory
      max_events: 500
      when_full: block
    request:
      retry_attempts: 10
      retry_max_duration_secs: 120
    healthcheck:
      enabled: false
EOF
  FAULT_ARGS=(--config "${FAULT_CONFIG}")
fi

echo "demo-agent[${HOSTNAME_TAG}]: starting vector (watch-config)"
vector --config "${STATIC_CONFIG}" --config "${FLEET_CONFIG}" "${FAULT_ARGS[@]}" --watch-config &
VECTOR_PID=$!
trap 'kill ${VECTOR_PID} 2>/dev/null || true' EXIT

# ── 5. Run the agent. Reload is a no-op success (Vector --watch-config does the
# actual reload on file change); validate uses the REAL vector binary. ─────────
export VORTEXFLOW_URL="${API}" INSTANCE_ID="${IID}" AGENT_TOKEN="${ATOK}" \
  AGENT_POLL_INTERVAL=10s \
  VECTOR_CONFIG_PATH="${FLEET_CONFIG}" \
  VECTOR_BIN="$(command -v vector)" \
  VECTOR_RELOAD_CMD=true
exec vortexflow-agent
