# Monitor fleet health

The **Health** dashboard and the **Instances** console show, at a glance, whether
your fleet is healthy, falling behind, or losing data. Metrics are pushed by each
Vector instance to VictoriaMetrics via `prometheus_remote_write` and read back by
VortexFlow — there is no agent polling overhead.

## Throughput, by events or by size

The dashboard's hero chart stacks throughput by fleet. Two controls shape it:

- **EPS / Size** — toggle the unit between **events per second** and **bytes per
  second**. The big number, the bands, and the per-fleet legend all switch with it.
- **Window** (15m / 1h / 6h / 24h) and **refresh interval** — pick the time range
  and how often the view updates.

Click a fleet in the legend to scope the chart (and the number) to just that fleet.

## Volume reduction

Under the throughput number, VortexFlow shows **volume reduction** — how much
smaller your egress is than your ingest:

```
659 KB/s in → 74 KB/s out · 89% reduced
```

This is the signature pipeline metric: it answers "is the pipeline actually saving
me money?" It's computed from Vector's source-received vs sink-sent bytes, and it
also appears per fleet on the fleet rows.

## Per-instance health

On the **Instances** console, each node shows its live event in/out and error
rates. When a node is unhealthy, extra chips appear (and stay hidden when it's
healthy, so a sick node stands out):

- **✕ drops/s** — events being discarded (data loss, e.g. a full buffer).
- **▮ buffer** — events queued in a sink buffer (backpressure — the sink can't
  keep up).
- **✦ sink-fail/s** — failed sink deliveries (HTTP 4xx/5xx responses).

These come from Vector's `internal_metrics`, so they reflect real component
behavior, not a probe.

## Needs attention & alerts

The dashboard's **Needs attention** panel surfaces the same signals as a triage
list — an instance dropping events shows red, a failing sink shows amber, along
with offline agents, failed config reloads, version drift, and expiring certs.

These conditions are also raised as first-class **events**: an instance dropping
events (critical) or with failing sink deliveries (warning) appears in the in-app
notification center and fires any configured
[notification channels](../administration/notifications.md) — so you're alerted
even when no one is looking at the dashboard. Thresholds are deliberately small
(drops > 1/s, sink failures > 0.5/s) to avoid flapping on a single blip.

## Related

- [Notifications](../administration/notifications.md) — wire health alerts to
  Slack / Teams / webhook / email.
- [Tap live events](live-tap.md) — drill from a number into the actual events.
- [Retention & disk](../administration/retention.md) — how long metrics are kept.
