# VortexFlow Docker deployment — design

Status: **agreed**, in progress (2026-06-17). The current `docker/docker-compose.yml`
is a skeleton — it references images with no Dockerfiles, mounts an `nginx.conf` /
`certs/` that don't exist, and there's no CI. This is the plan to make it a real,
self-hosted deploy that the agent fleet can actually talk to.

## Topology (agreed)

One front door, no redundant services:

```
            nginx  (80/443, TLS)         ← serves SPA, proxies API/install/vm
              ├── /            → SPA static (built frontend, baked into the image)
              ├── /api/*       → backend:8000
              ├── /install/*   → backend:8000   (install script + agent binary download)
              └── /vm/*        → victoriametrics:8428   (agents POST metrics here)
   backend  (uvicorn :8000)   ← FastAPI + agent binaries baked at /app/agent-bin
   postgres · redis · victoriametrics
```

Drop the separate `frontend` runtime service — the SPA is static, served by nginx.

## Backend image (the agent-critical piece)

Multi-stage:

1. `golang:<ver>` stage → `cd agent && make release` → linux/amd64 + linux/arm64 binaries.
2. `python:3.12-slim` stage → install `requirements.txt`, copy `app/`, copy the agent
   binaries into `/app/agent-bin/` (already the `agent_bin_dir` default — they line up),
   install `curl` (the healthcheck uses it). `CMD uvicorn app.main:app --host 0.0.0.0
   --port 8000`.

This is what makes `GET /install/agent/{os}/{arch}` serve a binary instead of 404.

## `public_url` (must-fix)

Behind nginx, `request.base_url` is the internal `http://backend:8000`, so the generated
`curl | sudo bash` one-liner and the metrics endpoint would point agents at an unreachable
address. Add a real `public_url` setting (`VORTEXFLOW_PUBLIC_URL`) to `config.py`; `install.py`
already prefers it over `request.base_url`. Required in any real deployment.

## nginx.conf

- `/api`, `/install` → backend:8000; `/vm` → victoriametrics:8428; `/` → SPA with
  `try_files … /index.html` fallback.
- `client_max_body_size` generous enough for cert/config uploads.
- TLS per below.

## TLS: self-signed by default → bring-your-own once configured

Secure out of the box, real cert when you want it:

- **First boot:** generate a self-signed cert + CA into a volume (an init step / entrypoint).
  nginx serves the self-signed cert.
- **Agents trust it without the insecure flag:** the install script ships the CA PEM to the
  host (`/etc/vortexflow/ca.crt`) and sets `AGENT_CA_CERT` in `agent.env`. **The Go agent
  gains a custom-CA option** — load `AGENT_CA_CERT` into its TLS `RootCAs` (small `client.go`
  change). `AGENT_INSECURE_SKIP_VERIFY` stays as a lab-only escape hatch.
- **Operator drops in a real cert:** mount it into nginx; publicly-trusted agents validate via
  system roots, and the bundled CA is simply redundant.

## Leader self-monitoring + demo

- **Leader self-monitoring:** a small Vector on the leader ships `internal_metrics` +
  `host_metrics` to the bundled VM, so the control plane's own health shows up. Host metrics
  from a container require mounting the host `/proc` and `/sys` (`PROCFS_ROOT`/`SYSFS_ROOT`);
  opt-in toggle for prod, on by default in the demo.
- **`docker-compose.demo.yml`:** overlay bundling one Vector + a local agent that converges on
  a demo fleet, so a fresh `docker compose up` shows data flowing and an agent going green.

## CI

GitHub Actions build + push `backend` and `nginx`(+SPA) images
multi-arch (linux/amd64+arm64) to ghcr under the project org (`ghcr.io/vortexflow-dev/…`).
The agent build lives inside the backend Dockerfile, so CI just needs Docker buildx.

## Build order

1. ✅ **Backend Dockerfile** (baked agent binaries) + `public_url`. `docker/backend.Dockerfile`.
2. ✅ **web image + nginx** (`docker/web.Dockerfile`, `nginx.conf`, shared `nginx-locations.conf`)
   + compose cleanup (one front door, org fix). Also fixed the broken frontend prod build.
3. ✅ **TLS** (Docker 3): first-boot self-signed CA+cert (`tls_bootstrap.py`), `GET /install/ca.crt`,
   nginx 443, install script ships the CA + verifies with `--cacert`, agent loads `AGENT_CA_CERT`.
   Verified end-to-end on the live HTTPS stack.
4. ✅ **Leader self-monitoring + demo** (Docker 4): `vector-leader` service ships host+internal
   metrics to VM (always-on); `docker-compose.demo.yml` adds an auto-registering demo-agent that
   converges. Leader metrics now surfaced on the dashboard (StatusStrip "leader load/mem" chip).
5. ✅ **CI** (Docker 5): `.github/workflows/build-images.yml` builds + pushes both images
   multi-arch to GHCR on main/tags. First run needs the GHCR package visibility set in org settings.

**All Docker milestones done.** Deploy = `docker compose build && up` (or pull images once CI has
published them). Set `VORTEXFLOW_SECRET_KEY` and `PUBLIC_URL`; TLS self-signed by default.

**Images are local-build-only until step 5** — nothing is pushed to ghcr. Run with
`docker compose -f docker/docker-compose.yml build` then `up` (set `VORTEXFLOW_SECRET_KEY`,
and `PUBLIC_URL` to the external https URL). TLS is on by default (self-signed); the dev loop
stays vite :5173 + uvicorn :8001.
