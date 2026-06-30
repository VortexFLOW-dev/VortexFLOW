# Upgrading VortexFlow

How to move a self-hosted deployment to newer versions. All image versions are
pinned in `docker/docker-compose.yml` so upgrades are deliberate, not surprises.

> **Before any upgrade: take a backup.** `pg_dump` the database **and** keep a
> copy of `VORTEXFLOW_SECRET_KEY` — VortexFlow encrypts component credentials,
> certificate keys, and notification secrets at rest with that key, so a database
> backup is unrecoverable without it. Full runbook:
> [Backup & Restore](guide/administration/backup-and-restore.md).

## Control plane (backend + web)

These are the VortexFlow images, built and published by CI (see
`.github/workflows/build-images.yml`).

```sh
# Pick a released version (tag) or :latest
VORTEXFLOW_VERSION=v1.2.3 docker compose -f docker/docker-compose.yml pull backend web
VORTEXFLOW_VERSION=v1.2.3 docker compose -f docker/docker-compose.yml up -d
```

The backend runs DB schema upgrades automatically on startup
(`_run_schema_upgrades()` — additive `ADD COLUMN IF NOT EXISTS`, no Alembic), so
no manual migration step is needed for control-plane upgrades.

## VictoriaMetrics

Low-risk, in-place. Bump the pinned tag and recreate:

```sh
# edit docker/docker-compose.yml: victoriametrics/victoria-metrics:vX.Y.Z
docker compose -f docker/docker-compose.yml up -d victoriametrics
```

The TSDB format is backward-compatible across minor versions; data in the
`vm_data` volume is preserved. Read the VM release notes before a major bump.

## Redis

In-place, low-risk (used only for ephemeral session/lockout state):

```sh
# bump redis:7-alpine → redis:8-alpine (etc.)
docker compose -f docker/docker-compose.yml up -d redis
```

## PostgreSQL — read this before a MAJOR bump

Minor upgrades (e.g. 16.2 → 16.4) are in-place: bump the tag, `up -d postgres`.

**Major upgrades (e.g. 16 → 17) are NOT in-place** — the data directory format
changes and the new image will refuse to start on an old data dir. Use a
dump/restore:

```sh
# 1. Dump with the OLD running container
docker compose -f docker/docker-compose.yml exec -T postgres \
  pg_dump -U vortexflow vortexflow > vortexflow-backup.sql

# 2. Stop, remove the old data volume
docker compose -f docker/docker-compose.yml down
docker volume rm vortexflow_postgres_data

# 3. Bump the postgres tag in docker-compose.yml, start fresh PG
docker compose -f docker/docker-compose.yml up -d postgres   # waits healthy

# 4. Restore
cat vortexflow-backup.sql | docker compose -f docker/docker-compose.yml exec -T \
  postgres psql -U vortexflow vortexflow

# 5. Bring the rest up
docker compose -f docker/docker-compose.yml up -d
```

Always take the `pg_dump` backup before any PostgreSQL change.

## Vector

The canonical Vector version lives in the `Makefile` (`VECTOR_VERSION`, currently
`0.56.0`). Three things must stay in sync with it:

1. The deployed image pins — `docker/docker-compose.yml` (vector-leader) and
   `docker/demo/agent.Dockerfile`.
2. The **component catalog** (the source/sink config forms). The backend image
   bundles the Vector binary and serves its `generate-schema` live, so the catalog
   tracks the deployed Vector automatically — **bump `VECTOR_VERSION` + the pins,
   rebuild the backend image, and the catalog follows** (no frontend rebuild; an
   admin can also hit "Refresh from Vector" on the Catalog page). The frontend also
   ships a **bundled fallback** for when Vector isn't reachable; regenerate it from
   the same converter the runtime uses:

   ```bash
   make catalog VECTOR_VERSION=0.57.0   # fetch the schema + regenerate the bundled fallback
   ```

   (Also update the Makefile `VECTOR_VERSION` default + the deployed pins above.)

Vector itself runs on the Vector hosts (managed instances), not in this compose —
installed/updated by the host's package manager (the install one-liner).
**Roadmap:** leader-driven version management — the agent reconciles each host to a
desired Vector version pushed from the control plane (see [ROADMAP.md](../ROADMAP.md)).
