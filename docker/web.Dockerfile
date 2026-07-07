# VortexFlow web image: builds the SPA and serves it via nginx, which also
# reverse-proxies the API, the agent install/download endpoints, and the metrics
# remote-write path. Build context is the repo root:
#   docker build -f docker/web.Dockerfile -t vortexflow-web .

# ── Stage 1: build the SPA ────────────────────────────────────────────────────
FROM node:25-alpine AS build
WORKDIR /app
# Pin pnpm to match the lockfile's toolchain. corepack otherwise pulls the latest
# pnpm, which handles build-script approval differently.
RUN corepack enable && corepack prepare pnpm@10.34.3 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
# Plain install (not --frozen-lockfile): frozen mode reads build-script approval
# from lockfile settings, skipping esbuild's build → ERR_PNPM_IGNORED_BUILDS. A
# plain install honors pnpm.onlyBuiltDependencies. Versions stay pinned by the lockfile.
RUN pnpm install
COPY frontend/ ./
RUN pnpm build

# ── Stage 2: nginx serving SPA + proxy ────────────────────────────────────────
FROM nginx:1.31-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY docker/nginx.conf /etc/nginx/conf.d/vortexflow.conf
COPY docker/nginx-locations.conf /etc/nginx/vortexflow-locations.conf
COPY docker/nginx-security-headers.conf /etc/nginx/vortexflow-security-headers.conf
COPY docker/nginx-force-https.conf /etc/nginx/vortexflow-force-https.conf
# Runs before nginx starts (official image runs /docker-entrypoint.d/*.sh); it
# enables the http->https redirect when VORTEXFLOW_FORCE_HTTPS is set.
COPY docker/40-vf-force-https.sh /docker-entrypoint.d/40-vf-force-https.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
