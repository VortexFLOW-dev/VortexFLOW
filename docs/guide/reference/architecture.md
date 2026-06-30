# Architecture

VortexFlow is a control plane: it stores your pipeline definitions, renders them
to Vector config, and ships that config to your Vector hosts. It does not sit in
the data path — your events flow through **Vector**, never through VortexFlow.

## Components

```
                         ┌──────────────────────────────┐
   operators / agents →  │  nginx (web)  ─ 80 / 443      │
                         │   ├── /api/*  → backend       │
                         │   └── /*      → React UI      │
                         └──────────────┬───────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
        ┌─────▼─────┐            ┌──────▼──────┐          ┌────────▼────────┐
        │ postgres  │            │   redis     │          │ victoriametrics │
        │ config DB │            │ sessions    │          │ Vector metrics  │
        └───────────┘            └─────────────┘          └─────────────────┘

        Vector hosts (your infrastructure, outside the stack)
        ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
        │ Vector + agent│   │ Vector (local)│   │ Vector + agent│  …
        └───────────────┘   └───────────────┘   └───────────────┘
```

| Service | Responsibility |
| --- | --- |
| **web (nginx)** | Single front door: serves the UI, proxies the API, terminates TLS. |
| **backend (FastAPI)** | The API and the render/deploy engine. |
| **postgres** | Source of truth — users, fleets, components, pipelines, history, audit, settings, certificates. |
| **redis** | Sessions, token revocation, brute-force counters. |
| **victoriametrics** | Stores Vector's internal metrics; powers the health dashboard. |

## How config reaches Vector

- **Local mode** — the backend writes rendered YAML to a directory the Vector
  process watches.
- **Agent mode** — the [VortexFlow agent](agent.md) on each host pulls the latest
  generation, validates it, and reloads Vector.

See [Render, Deploy & Rollout](../concepts/deploy-and-rollout.md).

## How VortexFlow reads Vector

- **Live topology & taps** — Vector's GraphQL API on each instance (default port
  8686).
- **Throughput & errors** — Vector's internal metrics, which Vector pushes to
  VictoriaMetrics via `prometheus_remote_write`; VortexFlow queries them for the
  dashboard.

## Data path vs. control path

This separation is the key property:

- **Control path** — VortexFlow ⇄ Vector config and API. Small, infrequent,
  authenticated.
- **Data path** — your events through Vector to your sinks. VortexFlow is **not**
  in it. If VortexFlow is down, your pipelines keep running.

## Persistence & schema

PostgreSQL is authoritative. The schema is provisioned and migrated automatically
on backend startup — there's no separate migration step to run. Configuration
that can live in the database (auth, SSO, general settings, TLS paths) does, with
environment variables as fallback.

## Deployment

The reference deployment is Docker Compose (see
[Installation](../getting-started/installation.md)). The backend image bundles
the agent binaries so hosts can fetch them from VortexFlow's install endpoint.

## Tech stack

- **Backend:** FastAPI (Python), SQLAlchemy async, PostgreSQL, Redis.
- **Frontend:** React + Vite + TypeScript, with a React Flow canvas.
- **Agent:** a single static Go binary, standard library only.
- **Front door:** nginx.
