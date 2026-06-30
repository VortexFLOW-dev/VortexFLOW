# Demo-agent image: a REAL Vector plus the vortexflow-agent, so the demo moves
# real data instead of stubbing the control loop. Build context is the repo root:
#   docker build -f docker/demo/agent.Dockerfile -t vortexflow-demo-agent .
# Demo only — talks to the backend over plain internal HTTP.

# ── Stage 1: build the agent binary for this image's arch ─────────────────────
FROM golang:1.26-bookworm AS agent-build
WORKDIR /src/agent
COPY agent/ ./
RUN CGO_ENABLED=0 go build -ldflags "-s -w" -o /out/vortexflow-agent .

# ── Stage 2: Vector runtime + agent ───────────────────────────────────────────
FROM timberio/vector:0.56.0-alpine
# bash for the entrypoint, curl for registration/seeding, ca-certificates for TLS.
RUN apk add --no-cache bash curl ca-certificates
COPY --from=agent-build /out/vortexflow-agent /usr/local/bin/vortexflow-agent
COPY docker/demo/demo-metrics.yaml /etc/vector/demo-metrics.yaml
COPY docker/demo/agent-entrypoint.sh /demo/agent-entrypoint.sh
ENTRYPOINT ["bash", "/demo/agent-entrypoint.sh"]
