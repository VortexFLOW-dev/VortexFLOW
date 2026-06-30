# Instances & Agents

An **instance** is a single Vector process that VortexFlow knows about. Instances
belong to a [fleet](fleets.md) and receive that fleet's rendered configuration.
This page explains the two ways an instance can receive config, and how the
VortexFlow agent works.

## Config push modes

Every instance has a **config push mode** that determines how the rendered
config reaches it:

### Local mode

VortexFlow writes the rendered config **file directly** to a directory that
Vector watches (`--watch-config`). This suits instances that VortexFlow can
reach and write to — for example a Vector running in the same Docker stack on a
shared volume.

- **How config arrives:** VortexFlow writes the file at deploy time.
- **What you configure:** the config directory path on the target.
- **Best for:** co-located Vectors, simple single-host setups, demos.

### Agent mode

A small companion process, the **VortexFlow agent**, runs on the Vector host and
**pulls** config from VortexFlow on an interval. This is the model for remote
fleets and anything you can't (or don't want to) reach inbound.

- **How config arrives:** the agent polls VortexFlow, fetches the latest
  generation, validates it, then reloads Vector.
- **What you configure:** almost nothing on the host — the install one-liner
  sets it up.
- **Best for:** distributed fleets, edge agents, anywhere pull beats push.

## How the agent works

The agent is a single static Go binary with no runtime dependencies. Its loop is
deliberately simple and safe:

1. **Register.** On first start the agent registers with VortexFlow using a
   fleet [bootstrap token](fleets.md#bootstrapping-new-members) and receives its
   own per-agent token.
2. **Poll.** It periodically calls `GET /agent/{id}/config`. VortexFlow returns
   the fleet's current config and **generation**; an `ETag` lets the agent skip
   work when nothing has changed.
3. **Validate, then reload.** When the generation advances, the agent writes the
   new config and runs `vector validate` **before** telling Vector to reload. If
   validation fails, it does **not** apply the change — it reports the failure
   instead, and the running Vector keeps serving the last good config.
4. **Report.** It posts status back (`applied_generation`, health, installed
   Vector version) so VortexFlow can show rollout convergence and drift.

This "validate-then-reload, never apply a bad config" contract is what makes
remote rollouts safe. A broken deploy is caught on the host and surfaced as an
alert rather than taking the pipeline down.

> The agent's credentials are written root-owned with `0600` permissions, and it
> trusts VortexFlow's CA so the pull channel is authenticated and encrypted. See
> [The VortexFlow agent](../reference/agent.md) for install details, the systemd
> unit, and the environment file.

## Health and topology

Regardless of push mode, VortexFlow reads each instance's **health and live
topology** directly from Vector's own API (Vector's GraphQL endpoint, by default
on port 8686). Throughput and error metrics come from Vector's internal metrics,
which Vector pushes to VictoriaMetrics via `prometheus_remote_write` for the dashboard.

This means even a purely local-mode or hand-managed Vector shows up with live
health as long as VortexFlow can reach its API.

## Version drift

Each instance reports the Vector version actually installed on its host.
VortexFlow compares that against the version its fleet desires (or the global
default) and flags **drift** — a host running an unexpected Vector version. Drift
is how you spot a half-finished rollout or a host that upgraded out of band. See
[Staged version rollout](../guides/version-rollout.md).

## Related

- [Fleets](fleets.md) — instances are grouped into fleets.
- [Render, Deploy & Rollout](deploy-and-rollout.md) — what "a deploy" actually does.
- [The VortexFlow agent](../reference/agent.md) — install and operate the agent.
