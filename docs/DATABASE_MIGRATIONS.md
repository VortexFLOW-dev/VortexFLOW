# Database migrations

VortexFlow's PostgreSQL schema is versioned with [Alembic](https://alembic.sqlalchemy.org/).
The SQLAlchemy models in `backend/app/models/` are the source of truth; every
schema change ships as a migration generated from them.

## Changing the schema

1. Edit the model(s) under `backend/app/models/` (add a column, table, index…).
2. Generate a migration from the diff:
   ```
   make migration m="add retention_days to fleets"
   ```
   This autogenerates a file in `backend/alembic/versions/` and formats it.
3. **Read the generated file.** Autogenerate is a first draft — check the
   `upgrade()`/`downgrade()` ops, add data backfills or server defaults it can't
   infer, and confirm it doesn't drop anything unexpected.
4. Commit the migration together with the model change.

The CI **migration drift guard** (`make migration-check` locally) applies all
migrations to a clean database and then runs `alembic check`; it fails if the
models have drifted from the migration graph — i.e. if you changed a model
without generating a migration.

## How migrations get applied

The backend applies migrations to `head` **on startup** (`_run_migrations()` in
`backend/app/main.py`), so a plain `docker compose up` / restart self-upgrades.
No separate migrate step is needed for a normal deploy. To apply them to the dev
database by hand: `make migrate`.

## Upgrading a pre-Alembic install (one-time cutover)

Databases provisioned by the original startup-DDL mechanism have no
`alembic_version` table. On the first boot of an Alembic-aware backend,
`_run_migrations()`:

1. Detects application tables but no `alembic_version`.
2. Runs `_legacy_ensure_baseline()` — the original idempotent DDL, but creating
   only the **frozen `0001` baseline table set** (never the live model metadata,
   which would also build tables added by later migrations and then collide with
   them). A database on **any** prior version is brought up to the `0001_baseline`
   schema, and only that.
3. **Stamps** the database at `0001_baseline` (records the version without
   re-creating anything).
4. Runs `upgrade head` to apply any migrations added after the baseline.

This was verified by building a database both ways (legacy DDL vs.
`alembic upgrade head`) and diffing `pg_dump --schema-only`: the application
schema is byte-identical. Fresh installs skip straight to `upgrade head`.

`_legacy_ensure_baseline()` is dead once every install carries `alembic_version`;
it's kept for safe direct upgrades from an old image and can be removed later.

## CLI reference

Run from `backend/` with the dev env loaded (`make` targets handle this):

| Command | Purpose |
|---|---|
| `make migration m="..."` | Autogenerate + format a new migration |
| `make migrate` | Apply migrations to the dev DB (`alembic upgrade head`) |
| `make migration-check` | Upgrade + `alembic check` — the CI drift gate |
| `alembic history` / `alembic current` | Inspect the migration graph / DB state |
| `alembic downgrade -1` | Roll back one revision (dev only) |
