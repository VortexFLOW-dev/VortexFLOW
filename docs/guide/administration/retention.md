# Retention & disk

VortexFlow stores two very different kinds of data, with separate retention controls.

## Metrics (VictoriaMetrics)

Per-fleet throughput, error rates, and Vector internal metrics are time-series in
VictoriaMetrics. **Retention is the main disk lever** — disk use ≈ retention ×
series cardinality.

Set in your deploy env (`docker/.env`):

| Variable | Default | What |
|---|---|---|
| `VM_RETENTION_PERIOD` | `30d` | How long metrics are kept (`90d`, `1y`, …). |
| `VM_MIN_FREE_DISK_BYTES` | `1073741824` (1 GiB) | Disk safety valve — VM refuses *writes* (rather than fill the disk) once free space drops below this. |

After changing, restart VictoriaMetrics. To keep cardinality (and therefore disk)
in check, use the per-instance **`expire_metrics_secs`** setting to drop stale series.

30 days is plenty for operations; 90 days–1 year suits longer security trend
analysis if you have the disk.

## Database (Postgres)

The relational database holds **config + operational data** (users, fleets,
components, tokens, and the audit log) — *not* time-series, so it doesn't grow with
ingest volume. A few tables do grow over time on a busy install: **`audit_log`**,
**`events`**, and the **`notification_deliveries`** outbox.

A daily background sweep prunes rows older than a configured age. **Each is opt-in;
`0` (the default) means keep forever** — nothing is deleted unless you choose to.

| Variable | Default | Prunes |
|---|---|---|
| `AUDIT_RETENTION_DAYS` | `0` (keep forever) | `audit_log` entries older than N days |
| `EVENT_RETENTION_DAYS` | `0` (keep forever) | `events` older than N days |
| `NOTIFICATION_RETENTION_DAYS` | `0` (keep forever) | delivery records older than N days |

> **Audit logs are compliance-sensitive.** They default to keep-forever — only set
> `AUDIT_RETENTION_DAYS` if you have a defined retention requirement.

Recommended starting point for a busy deployment: `AUDIT_RETENTION_DAYS=365`,
`EVENT_RETENTION_DAYS=90`, `NOTIFICATION_RETENTION_DAYS=30`. The sweep runs every
`VORTEXFLOW_RETENTION_SWEEP_HOURS` hours (default 24).

Postgres disk usage is otherwise just the size of its volume — back it up (and the
secret key) per [Backup & Restore](backup-and-restore.md).

## Dashboard time window

The Health dashboard's throughput chart has a window selector (**15m / 1h / 6h /
24h**) next to the auto-refresh control (Off / 10s / 30s / 60s). The window only
changes how much history the chart renders; it doesn't affect retention.
