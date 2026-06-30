# Installation

VortexFlow is distributed as a set of containers orchestrated with Docker
Compose. This page covers a real deployment against your own Vector instances.
For a throwaway evaluation with a bundled Vector, use the
[Quickstart](quickstart.md) demo stack instead.

## Architecture at a glance

A VortexFlow deployment is a small set of services behind a single nginx front
door:

```
nginx (web)  ─ 80 / 443
  ├── /api/*  →  backend (FastAPI)
  │               ├── postgres   — users, fleets, components, pipelines, audit
  │               ├── redis      — sessions, brute-force counters
  │               └── victoriametrics — Vector internal metrics (health dashboard)
  └── /*      →  the React UI (static files)
```

Your Vector instances live **outside** this stack — VortexFlow connects out to
them (local-write mode) or they pull config from it (agent mode). See
[Instances & Agents](../concepts/instances-and-agents.md) and
[Architecture](../reference/architecture.md) for detail.

## Requirements

- A Linux host with Docker and Docker Compose v2.
- Inbound access on 443 (and 80, which redirects to 443) for operators and for
  agents that pull config.
- Outbound access to any Vector instances you manage in **local-write** mode.

## 1. Get the images

VortexFlow ships multi-arch images. Build them locally from the repo:

```bash
docker compose build
```

(Once the public release publishes images to a registry, you'll be able to
`docker compose pull` instead of building.)

## 2. Configure

Backend configuration comes from `config.yaml` with environment-variable
overrides. The settings you'll most likely set for a real deployment:

| Setting | Purpose |
| --- | --- |
| `public_url` | The externally reachable base URL (e.g. `https://vortexflow.example.com`). Agents and SSO redirects use it. |
| Database / Redis URLs | Point at the bundled services or your own managed instances. |
| TLS | Self-signed CA by default; supply your own cert via the UI or mounted files. See [TLS & Certificates](../administration/tls-certificates.md). |

> **Secrets:** never commit real secrets. Use an `.env` file or your
> orchestrator's secret mechanism. The agent's credentials are written
> root-owned with `0600` permissions on each Vector host (see
> [The VortexFlow agent](../reference/agent.md)).

## 3. Start

```bash
docker compose up -d
```

Then browse to your `public_url` (or `https://localhost` for a local install).

## First admin

Unlike the demo stack, a fresh install does **not** seed a default account.
Instead, an **admin recovery token** is printed to the backend logs on startup:

```bash
docker compose logs backend | grep -i recovery
```

Open `/recovery`, paste the token, and create your first administrator. From
there, add users and configure SSO under
[Authentication & SSO](../administration/authentication.md). The recovery path
stays available as a break-glass even after SSO is enabled.

## 4. Connect Vector

With VortexFlow running, add your first Vector instance and assign it to a
fleet. Follow [Connect a Vector instance](../guides/connect-an-instance.md).

## TLS

By default VortexFlow generates a self-signed CA so the stack — and agents that
trust that CA — work out of the box. For anything beyond local testing, install
a real certificate; see [TLS & Certificates](../administration/tls-certificates.md).

## Upgrades

VortexFlow has two independent upgrade planes:

- **The VortexFlow application** — upgrade by pulling new images and running
  `docker compose up -d`. The database schema is migrated automatically on
  startup.
- **Vector itself, on your hosts** — managed per fleet as a staged rollout. See
  [Staged version rollout](../guides/version-rollout.md).

See the repository's `docs/UPGRADING.md` for version-specific notes.
