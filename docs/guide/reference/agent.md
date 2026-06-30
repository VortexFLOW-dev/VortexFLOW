# The VortexFlow agent

The **VortexFlow agent** is the small companion process that runs on a Vector
host in [agent mode](../concepts/instances-and-agents.md#agent-mode). It pulls
configuration from VortexFlow, validates it, and reloads Vector — so remote and
distributed fleets are managed without VortexFlow needing inbound access to each
host.

It is a single **static Go binary** built against the standard library, so there
are no runtime dependencies to install.

## Installation

Each [fleet](../concepts/fleets.md) provides an install one-liner that embeds the
fleet ID and a reusable bootstrap token:

```bash
curl -sL https://<your-vortexflow>/install/fleet/<fleet-id>?token=<token> | sudo bash
```

The installer:

1. Downloads the correct agent binary for the host's OS and architecture from
   VortexFlow's install endpoint.
2. Writes a **systemd unit** (`vortexflow-agent`).
3. Writes a **root-owned environment file** with mode `0600` containing the
   agent's credentials and VortexFlow's address.
4. Enables and starts the service.

The agent then registers itself into the fleet and begins polling.

## Lifecycle

1. **Register** — exchanges the fleet bootstrap token for its own per-agent token.
2. **Poll** — calls `GET /agent/{id}/config` on an interval; an `ETag` /
   generation check means it only does work when config actually changed.
3. **Validate-then-reload** — on a new generation, writes the config and runs
   `vector validate` **before** reloading Vector. If validation fails it does not
   apply the change and reports the failure; the running Vector keeps its last
   good config.
4. **Report** — posts status (`applied_generation`, health, installed Vector
   version) so VortexFlow can show rollout convergence and
   [drift](../concepts/instances-and-agents.md#version-drift).

## Security

- The environment file holding credentials is **root-owned, `0600`**.
- The agent trusts VortexFlow's CA, so the pull channel is authenticated and
  encrypted — including when VortexFlow uses its default
  [self-signed CA](../administration/tls-certificates.md#default-self-signed-ca).
- Communication is **outbound from the host** to VortexFlow; no inbound port on
  the Vector host is required for config delivery.

## Operating

- **Status:** `systemctl status vortexflow-agent`
- **Logs:** `journalctl -u vortexflow-agent -f`
- **Restart:** `systemctl restart vortexflow-agent`

A healthy agent shows up against its instance in VortexFlow with a current
applied generation and live health.

## Local mode vs. agent mode

You don't need the agent for every host. A Vector that VortexFlow can write to
directly can run in [local mode](../concepts/instances-and-agents.md#local-mode)
instead. Use the agent where pull beats push: remote hosts, edge fleets, and
anything behind NAT.
