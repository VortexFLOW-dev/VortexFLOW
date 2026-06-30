# Backup & Restore

VortexFlow's state lives in **PostgreSQL** (users, fleets, components, pipelines,
history, certificates, settings). Backing it up is a `pg_dump`. But there's one
thing a database dump alone won't save you — read the next section first.

## ⚠️ Back up your secret key with the database

VortexFlow **encrypts secrets at rest** — component credentials, certificate
private keys, and notification channel secrets are all Fernet-encrypted with a
key derived from **`VORTEXFLOW_SECRET_KEY`**.

That means: **a database backup is useless without the matching `VORTEXFLOW_SECRET_KEY`.**
If you restore the database but have lost the key, every encrypted secret —
sink passwords, TLS private keys, webhook tokens — is **unrecoverable** and must
be re-entered by hand.

> Back up `VORTEXFLOW_SECRET_KEY` (it lives in your `.env` / secret store)
> **separately and securely**, and keep it for the life of any backup you might
> restore from. Treat it like the root credential it is.

## What to back up

| Item | How | Critical? |
| --- | --- | --- |
| **PostgreSQL** | `pg_dump` (below) | **Yes** — the source of truth |
| **`VORTEXFLOW_SECRET_KEY`** | from your `.env` / secret manager | **Yes** — decrypts the above |
| **TLS certificates** | the `certs` volume (or re-apply from the cert store) | If using a real cert; the self-signed CA regenerates |
| **`.env`** | your config | Recommended |
| VictoriaMetrics data | the `vm_data` volume | No — metrics regenerate |
| Redis | — | No — ephemeral sessions/lockouts |

## Routine backup

Take a logical dump of the database (run on a schedule — e.g. nightly cron):

```bash
docker compose exec -T postgres \
  pg_dump -U vortexflow vortexflow > vortexflow-$(date +%F).sql
```

Store the dump **and** a copy of `VORTEXFLOW_SECRET_KEY` together in your backup
location (encrypted at rest). Rotate/retain per your policy.

## Restore (disaster recovery)

Restore onto a fresh stack configured with the **same `VORTEXFLOW_SECRET_KEY`**.

```bash
# 1. Bring up a fresh stack with the SAME VORTEXFLOW_SECRET_KEY in .env.
docker compose up -d postgres            # wait until healthy

# 2. Restore the dump.
cat vortexflow-2026-06-20.sql | docker compose exec -T postgres \
  psql -U vortexflow vortexflow

# 3. Bring up the rest.
docker compose up -d
```

The backend re-applies any additive schema upgrades on startup, so a dump from an
older version restores cleanly onto a newer build.

## Verify a backup

A backup you haven't tested isn't a backup. Periodically restore a dump into a
**scratch database** and confirm the row counts match the live one — this is the
exact check we run, and it round-trips cleanly:

```bash
docker compose exec -T postgres psql -U vortexflow -d postgres \
  -c "CREATE DATABASE vftest;"
cat vortexflow-backup.sql | docker compose exec -T postgres \
  psql -U vortexflow -d vftest
docker compose exec -T postgres psql -U vortexflow -d vftest -c \
  "select count(*) from users; select count(*) from fleets; select count(*) from components;"
docker compose exec -T postgres psql -U vortexflow -d postgres \
  -c "DROP DATABASE vftest;"
```

Then sign in to the restored instance and confirm an encrypted secret still works
(e.g. deploy a fleet whose sink uses a stored credential) — that proves the
secret key matches the data.

## Related

- [Installation](../getting-started/installation.md) — where `VORTEXFLOW_SECRET_KEY` is set.
- `docs/UPGRADING.md` — version upgrades (always back up first).
