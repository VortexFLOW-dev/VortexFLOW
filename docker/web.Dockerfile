# VortexFlow web image: builds the SPA and serves it via nginx, which also
# reverse-proxies the API, the agent install/download endpoints, and the metrics
# remote-write path. Build context is the repo root:
#   docker build -f docker/web.Dockerfile -t vortexflow-web .

# ── Stage 1: build the SPA ────────────────────────────────────────────────────
FROM node:22-alpine AS build
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
FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY docker/nginx.conf /etc/nginx/conf.d/vortexflow.conf
COPY docker/nginx-locations.conf /etc/nginx/vortexflow-locations.conf
COPY docker/nginx-security-headers.conf /etc/nginx/vortexflow-security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
