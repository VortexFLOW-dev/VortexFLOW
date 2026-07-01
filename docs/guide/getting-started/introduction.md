# Introduction

VortexFlow is a free, self-hosted, open-source **control plane for [Vector](https://vector.dev)**.
Vector is an excellent pipeline _engine_ — fast, reliable, vendor-neutral — but
on its own it leaves you hand-editing YAML files and SSHing into boxes to check
whether data is still flowing. VortexFlow is the cockpit: build pipelines
visually, deploy them across a whole fleet of Vector hosts, and watch throughput,
errors, and rollout health from one place.

It is a free, self-hosted alternative to the commercial observability-pipeline
managers — useful to any team running Vector
(platform engineering, DevOps, security operations), regardless of where your
data ultimately lands.

## What VortexFlow does

- **Build pipelines visually.** Sources, transforms, routes, and sinks are nodes
  on a drag-and-drop DAG canvas. See your whole topology instead of
  reverse-engineering it from config files.
- **Manage a fleet.** Group Vector instances into [Fleets](../concepts/fleets.md)
  that share one configuration. Assign agent or aggregator roles and bootstrap a
  new host with a single install command.
- **Render and deploy.** VortexFlow compiles a fleet's topology into one valid
  Vector configuration and publishes it to every member —
  [pull-based agents](../concepts/instances-and-agents.md) validate-then-reload,
  or it writes the file directly in local mode.
- **Roll out safely.** Pin a Vector version per fleet and upgrade one fleet at a
  time. Every deploy is gated by a server-side `vector validate` and a
  port-collision lint, so a bad change can't take the fleet down.
- **Operate.** A live [health dashboard](../guides/monitor-fleet-health.md) —
  throughput by fleet (events or bytes), volume reduction, per-instance health
  (drops, backpressure, sink-delivery failures) with alerting, errors, and rollout
  convergence — plus [live event taps](../guides/live-tap.md) on any node (including
  a before/after-a-transform compare), config version history with rollback, and
  notifications.
- **Author transforms.** A [VRL editor](../concepts/transforms-and-vrl.md) with
  syntax highlighting and an input → output preview, plus a reusable transform
  library so you stop copy-pasting remaps between hosts.

## What VortexFlow is **not**

- **Not a log search or analytics tool.** There is no query UI or data
  exploration — VortexFlow manages the pipeline, not the data that flows through it.
- **Not a runtime.** VortexFlow generates and reads configuration; Vector does
  the actual work of moving data.
- **Not a metrics visualization tool.** Use Grafana for dashboards on your data.
- **Not a SaaS product.** It is self-hosted only — no phone-home, no telemetry,
  no license check.

## Zero lock-in

Everything VortexFlow writes is the exact standard Vector YAML you would have
hand-written — no proprietary fields, no wrappers. It drops cleanly into the
GitOps and CI workflows you already trust, and the day you stop using VortexFlow,
your Vector configuration keeps running untouched.

## How it fits with Vector

VortexFlow talks to Vector through Vector's own interfaces:

| VortexFlow uses… | …for |
| --- | --- |
| Vector configuration (YAML) | the artifact it renders and deploys |
| Vector's GraphQL API | reading live topology and tapping events |
| Vector's internal metrics | the health dashboard (Vector pushes them to VictoriaMetrics via `prometheus_remote_write`) |
| `vector validate` | the pre-deploy safety gate |

Because the contract is Vector's own config and API, VortexFlow stays honest as
Vector evolves — for example, the [source and sink catalog](../concepts/pipelines-and-flow.md)
is generated from Vector's published JSON schema rather than hand-maintained.

## Next steps

- New here? Read about [Fleets](../concepts/fleets.md) — the central concept.
- Want it running now? Follow the [Quickstart](quickstart.md).
