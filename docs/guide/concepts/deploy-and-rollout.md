# Render, Deploy & Rollout

This is the engine of VortexFlow: how the pipeline you build on the
[Flow canvas](pipelines-and-flow.md) becomes one validated Vector configuration
and reaches every host in a [fleet](fleets.md). Understanding this loop explains
most of what VortexFlow does.

## The loop

```
build  →  render  →  validate  →  deploy  →  observe
```

1. **Build** — define sources, transforms, routes, and sinks on the fleet.
2. **Render** — VortexFlow compiles the fleet's components into a single valid
   Vector config (standard YAML).
3. **Validate** — the rendered config is checked before anything is shipped.
4. **Deploy** — the config is published to every member instance and the fleet's
   [generation](fleets.md#generation) advances.
5. **Observe** — instances apply the new generation and report back; you watch
   convergence, throughput, and errors.

## Render

VortexFlow's render step assembles everything on a fleet — components, their
catalog form values, transform stages, and routes — into one Vector
configuration. Components are wired by reference: a transform stage declares its
inputs, a route consumes stages or sources, and sinks consume whatever feeds
them, producing a `source → remap → route → sink` graph in the output.

Per-host settings (like a host's data directory or metric-expiry window) are
merged in at deploy time, so the shared fleet config stays clean while each host
still gets its host-specific globals.

You can always **preview** the rendered YAML before deploying — open the fleet's
**Config** view. What you see is exactly what Vector will run; there are no
proprietary fields or hidden wrappers.

## Validate — the pre-deploy gate

Every deploy is gated by safety checks, so a broken change can't take a fleet
down:

- **`vector validate`** — VortexFlow runs Vector's own validator against the
  rendered config server-side. If Vector would reject it, the deploy is blocked.
- **Bind-collision lint** — VortexFlow checks that no two components try to bind
  the same address/port (a common, easy-to-miss mistake when combining sources),
  and blocks the deploy if they would clash.

If a gate fails, you get the error up front in the UI rather than discovering it
when Vector falls over.

> Defense in depth: even after the server-side gate, [agent-mode](instances-and-agents.md#agent-mode)
> hosts validate the config **again locally** before reloading Vector, and refuse
> to apply anything that doesn't pass.

## Deploy

How the validated config reaches a host depends on its
[push mode](instances-and-agents.md#config-push-modes):

- **Local mode** — VortexFlow writes the config file to the instance's watched
  directory; Vector picks it up.
- **Agent mode** — the new generation is published; each agent pulls it on its
  next poll, validates locally, and reloads Vector.

Deploying advances the fleet's **generation** counter. That single number is how
the system tracks "what should every host be running right now."

## Rollout & convergence

Because each instance reports the generation it has **applied**, VortexFlow can
show whether a fleet has converged:

- **Converged** — every member is on the current generation (`42/42`).
- **Rolling out** — some members are still on a prior generation (agents that
  haven't polled yet, or a host that's down).
- **Failed** — a member reported that validation or reload failed; it keeps
  running its last good config and raises an alert.

This is intentionally **not** all-or-nothing. A slow or offline host doesn't
block the others; you simply see it lag and converge when it returns.

## Two upgrade planes

Deploying **config** is separate from upgrading the **Vector binary**:

- **Config rollout** — described above; advances the fleet generation.
- **Vector version rollout** — a fleet can pin a desired Vector version, and
  agents reconcile the installed binary toward it. This lets you upgrade Vector
  itself one fleet at a time. See
  [Staged version rollout](../guides/version-rollout.md).

## History & rollback

Pipeline changes are versioned. You can review a pipeline's history and **roll
back** to an earlier version; the restore is itself recorded, so the history
stays append-only and auditable.

## Related

- [Fleets](fleets.md) and [Instances & Agents](instances-and-agents.md) — the pieces this loop ties together.
- [Deploy to a fleet](../guides/deploy-to-a-fleet.md) — do it hands-on.
- [Staged version rollout](../guides/version-rollout.md) — the Vector-binary plane.
