# VortexFlow backend image. Build context is the repo root:
#   docker build -f docker/backend.Dockerfile -t vortexflow-backend .
#
# Multi-stage: build the Go agent binaries, then bake them into the Python image
# at /app/agent-bin so GET /install/agent/{os}/{arch} can serve them.

# Vector version to bundle (live catalog + validate gate). Global ARG so it can be
# used in a FROM line below — `COPY --from` doesn't support variable image refs.
ARG VECTOR_VERSION=0.56.0

# ── Stage 0: Vector binary (glibc/debian, matches the python:slim base) ────────
FROM timberio/vector:${VECTOR_VERSION}-debian AS vector

# ── Stage 1: agent binaries ───────────────────────────────────────────────────
FROM golang:1.26-bookworm AS agent-build
ARG VERSION=dev
WORKDIR /src/agent
COPY agent/ ./
# Static, stripped binaries for the platforms agents run on (Linux hosts).
RUN set -eux; \
    for arch in amd64 arm64; do \
      CGO_ENABLED=0 GOOS=linux GOARCH="$arch" \
        go build -ldflags "-s -w -X main.version=${VERSION}" \
        -o "/out/vortexflow-agent-linux-${arch}" .; \
    done

# ── Stage 2: python deps (build wheels with native toolchain) ─────────────────
FROM python:3.14-slim AS py-build
# python3-saml → lxml + xmlsec may need a compiler / xmlsec headers if no wheel
# is available for the platform. Build into a venv we copy into the runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config libxml2-dev libxmlsec1-dev libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 3: runtime ──────────────────────────────────────────────────────────
FROM python:3.14-slim
# Runtime libs for xmlsec/lxml + curl for the container healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libxml2 libxmlsec1 libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=py-build /venv /venv
ENV PATH="/venv/bin:$PATH"
WORKDIR /app
COPY backend/app ./app
COPY --from=agent-build /out/ /app/agent-bin/
# Bundle the Vector binary (from the stage above) so the server can run
# `vector generate-schema` (live source/sink catalog) and `vector validate`
# (pre-deploy gate). Keep VECTOR_VERSION in sync with the Makefile / deployed pins.
COPY --from=vector /usr/bin/vector /usr/local/bin/vector
ENV VORTEXFLOW_AGENT_BIN_DIR=/app/agent-bin \
    VORTEXFLOW_VECTOR_BIN=/usr/local/bin/vector \
    PYTHONUNBUFFERED=1
# Run unprivileged. Pre-create + own /certs so the named volume mounted there is
# writable by this user (the backend generates its self-signed CA/cert here on
# first boot). No home dir is needed; HOME points at the writable tmpfs.
RUN useradd --system --uid 10001 --user-group --no-create-home appuser \
    && mkdir -p /certs \
    && chown appuser:appuser /certs
ENV HOME=/tmp
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
