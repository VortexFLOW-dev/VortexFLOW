# Quickstart

This walks you from nothing to a running VortexFlow with a live Vector instance
in a few minutes, using the bundled **demo** stack. The demo stack adds a
self-registering Vector agent and a metrics generator on top of the normal
deployment, so you can see fleets, health, and live taps working immediately
without wiring up your own hosts first.

> For a real deployment against your own Vector instances, see
> [Installation](installation.md) instead.

## Prerequisites

- Docker and Docker Compose (Compose v2 — the `docker compose` subcommand).
- About 2 GB of free memory for the full stack (backend, web, PostgreSQL, Redis,
  VictoriaMetrics, and the demo Vector agent).

## 1. Start the stack

From the repository root:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d
```

This builds and starts:

| Service | Role |
| --- | --- |
| `web` | nginx front door — serves the UI and proxies the API (ports 80 / 443) |
| `backend` | the VortexFlow API |
| `postgres` | configuration store |
| `redis` | sessions and brute-force counters |
| `victoriametrics` | stores Vector's internal metrics for the health dashboard |
| `demo-agent` | a real Vector instance that registers itself into a fleet |

The first run builds images and may take a minute. Watch progress with
`docker compose logs -f backend`.

## 2. Open the UI

Browse to **https://localhost**. The demo stack uses a self-signed certificate,
so your browser will warn once — accept it to continue (or see
[TLS & Certificates](../administration/tls-certificates.md) to install a real
cert).

## 3. Sign in

The demo stack seeds an administrator account:

- **Email:** `admin@example.com`
- **Password:** `ChangeMe123!`

You'll be prompted to set a new password on first sign-in. (On a non-demo
install there is no seeded account — an admin recovery token is printed to the
logs at startup instead; see [Installation](installation.md#first-admin).)

## 4. Look around

Once you're in, the demo data gives you something to explore:

- **Health** — the home dashboard. You should see throughput climbing as the demo
  agent reports metrics, broken down by fleet.
- **Fleets** — the demo agent has registered into a fleet. Open it to see its
  members and their rollout state. ([Fleets](../concepts/fleets.md))
- **Flow** — the visual pipeline canvas for the selected fleet. Add a source or a
  transform and watch it render. ([Pipelines & Flow](../concepts/pipelines-and-flow.md))
- **Live Tap** — sample real events flowing through the demo agent. Pick the
  demo's transform and toggle **Compare before/after** to see the remap's effect.
  ([Tap live events](../guides/live-tap.md))

> **See the unhealthy states too.** To watch the health chips and the "Needs
> attention" alerts light up, add the fault overlay — it brings up a deliberately
> failing `chaos-agent` (dropping events, full buffers, 503s) in its own fleet,
> leaving the healthy demo untouched:
>
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.demo.yml \
>   -f docker-compose.faults.yml up -d
> ```
>
> Remove it with `docker rm -f chaos-agent vortexflow-fault-sink-1`. See
> [Monitor fleet health](../guides/monitor-fleet-health.md).

## 5. Make your first change

A good first end-to-end loop:

1. In **Flow**, add a source and a sink to the demo fleet.
2. Open the fleet's **Config** view to preview the rendered Vector YAML.
3. Click **Deploy**. VortexFlow validates the config, then publishes it to the
   demo agent, which reloads Vector. ([Render, Deploy & Rollout](../concepts/deploy-and-rollout.md))

That's the core workflow: **build → render → validate → deploy → observe.**

## Tearing down

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml down
```

Add `-v` to also remove the volumes (PostgreSQL and metrics data) for a fully
clean slate.

## Next steps

- Understand the model: [Fleets](../concepts/fleets.md) and
  [Instances & Agents](../concepts/instances-and-agents.md).
- Ready to point it at real hosts? [Installation](installation.md) and
  [Connect a Vector instance](../guides/connect-an-instance.md).
