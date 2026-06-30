# VortexFlow Documentation

VortexFlow is the open-source control plane for your [Vector](https://vector.dev)
fleet. Build pipelines visually, then deploy them across every Vector host you
run — with staged version rollouts, pre-deploy validation, and live event taps,
all from one self-hosted UI. Everything it writes is standard Vector YAML, so
there is no lock-in.

This is the user and operator guide. If you are evaluating VortexFlow, start with
the [Introduction](getting-started/introduction.md); if you just want it running,
jump to the [Quickstart](getting-started/quickstart.md).

> **Status:** VortexFlow is pre-1.0 and under active development. These docs track
> `main`. Anything marked _planned_ is not shipped yet.

## Getting Started

- [Introduction](getting-started/introduction.md) — what VortexFlow is, who it's for, and how it relates to Vector.
- [Quickstart](getting-started/quickstart.md) — get a working instance with the bundled demo in a few minutes.
- [Installation](getting-started/installation.md) — Docker Compose deployment, configuration, and TLS.

## Core Concepts

- [Fleets](concepts/fleets.md) — the unit of deployment: a named group of Vector instances that share one config.
- [Instances & Agents](concepts/instances-and-agents.md) — how VortexFlow connects to Vector, in local-write or agent (pull) mode.
- [Pipelines & Flow](concepts/pipelines-and-flow.md) — sources, transforms, routes, and sinks on the visual DAG canvas.
- [Render, Deploy & Rollout](concepts/deploy-and-rollout.md) — how a fleet becomes one validated Vector config and reaches every host.
- [Transforms & VRL](concepts/transforms-and-vrl.md) — the VRL editor, live preview, and the reusable transform library.

## Guides

- [Connect a Vector instance](guides/connect-an-instance.md)
- [Build a pipeline in Flow](guides/build-a-pipeline.md)
- [Deploy to a fleet](guides/deploy-to-a-fleet.md)
- [Staged version rollout](guides/version-rollout.md)
- [Monitor fleet health](guides/monitor-fleet-health.md)
- [Tap live events](guides/live-tap.md)

## Administration

- [Authentication & SSO](administration/authentication.md) — local accounts plus Entra ID, OIDC, SAML, and LDAP.
- [Roles & RBAC](administration/rbac.md) — Admin, Editor, and Viewer.
- [TLS & Certificates](administration/tls-certificates.md)
- [Notifications](administration/notifications.md)
- [White-labeling](administration/white-labeling.md)
- [Backup & Restore](administration/backup-and-restore.md) — back up the database **and the secret key**.
- [Retention & disk](administration/retention.md) — metrics retention + DB pruning.

## Reference

- [Architecture](reference/architecture.md)
- [The VortexFlow agent](reference/agent.md)
- [FAQ](reference/faq.md)

---

VortexFlow is free and open source under the [MPL 2.0](https://www.mozilla.org/MPL/2.0/)
license — the same license as Vector itself.
