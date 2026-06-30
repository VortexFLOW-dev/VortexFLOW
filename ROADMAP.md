# Roadmap

VortexFlow is built in the open and shipped in phases. This is where it's headed
after the v1 release — directional, not dated. Have an opinion on priorities?
Open an issue.

Shipped features are described in the [README](README.md), and every release is
recorded in the [CHANGELOG](CHANGELOG.md).

## Next

- **AI-operable control plane (MCP)** — a [Model Context Protocol](https://modelcontextprotocol.io)
  server that exposes the same tools the in-app AI assistant already uses
  (generate and validate VRL, tap a sample event, render/validate/deploy a fleet)
  to external agents — behind the same authentication, RBAC, and audit log as a
  human operator. One tool layer, two front doors.

## Exploring

- **Pipeline packs** — shareable, importable transform and config bundles.
- **Cribl config import** — bring an existing Cribl pipeline into VortexFlow.
- **Hierarchical fleets** — parent/child fleets with inherited, overridable config.
- **Leader-driven Vector upgrades** — manage the Vector *binary* version per fleet
  (staged/canary rollout), not just its configuration.
- **Instance-scoped RBAC** — per-fleet roles (e.g. Editor on staging, Viewer on prod).
