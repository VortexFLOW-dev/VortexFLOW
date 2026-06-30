# Fleets

A **fleet** is the central concept in VortexFlow. It is a named group of Vector
instances that share **one rendered configuration**. The fleet — not the
individual host — is the unit you build for and the unit you deploy.

If you've used Cribl, a fleet maps to a Worker Group or an Edge Fleet. If you've
used Vector directly, a fleet is "a set of Vector nodes that should all run the
same config."

## Why fleets

Managing Vector host-by-host doesn't scale: the same pipeline ends up
copy-pasted into many config files that drift apart. VortexFlow inverts that —
you define the pipeline **once on the fleet**, and every member instance receives
the same rendered config. Add a host to the fleet and it inherits the config;
change the pipeline and every member converges.

## What lives on a fleet

A fleet owns the pipeline definition that gets rendered into Vector config:

- **Components** — [sources and sinks](pipelines-and-flow.md) from the catalog.
- **Transforms** — remap/VRL stages. ([Transforms & VRL](transforms-and-vrl.md))
- **Routes** — conditional branching between components.

These are assembled at deploy time into a single valid Vector configuration.
See [Render, Deploy & Rollout](deploy-and-rollout.md) for how that works.

## The default fleet

Every VortexFlow install seeds a **Default** fleet on first boot. It cannot be
deleted — it's the home for any instance you haven't placed elsewhere. Create
additional fleets to separate environments, regions, or tiers (for example
`edge-agents`, `eu-aggregators`, `k8s-prod`).

## Deleting a fleet

Deleting a fleet is destructive: it **permanently deletes all of that fleet's
configuration** (sources, sinks, transforms, routes) and **unassigns every
instance** in it (the instances themselves are not deleted — they simply leave the
fleet). To prevent accidents, the delete dialog shows the exact blast radius —
how many components and routes will be deleted and which instances will be
detached — and requires you to **type `DELETE`** to confirm.

Deleting an individual **source, sink, transform, or route** that is still wired
to others is blocked with an "in use by …" message naming what references it;
unwire it first, or use the explicit **force-delete** to remove it anyway (force
deletes are recorded in the [audit log](../administration/rbac.md)).

## Instance roles

Within a fleet, each member instance has a **role**, using Vector's own
terminology:

- **Agent** — a Vector running close to the data source (on a host, a node, a
  container) collecting and forwarding events.
- **Aggregator** — a Vector that receives from many agents, does heavier
  processing, and fans out to sinks.

Roles are descriptive metadata today; they document the topology and inform how
you organize fleets. See [Instances & Agents](instances-and-agents.md) for how
instances actually connect.

## Generation

Each fleet carries a **generation** counter. Every time you deploy, the
generation increments. Member instances report which generation they have
applied, so VortexFlow can show you, at a glance, whether the fleet has
**converged** on the latest config or whether some hosts are still catching up.

This is the basis of the rollout view: `42/42` members on the current generation
means a fully rolled-out fleet.

## Per-fleet Vector version

A fleet can pin its own **desired Vector version**, overriding the global
default. This is what makes staged upgrades possible — bump one fleet to a new
Vector version and leave the rest untouched. Drift between a host's installed
version and its fleet's desired version is surfaced as a warning.

See [Staged version rollout](../guides/version-rollout.md).

## Bootstrapping new members

Each fleet has a reusable **bootstrap token**. Combined with the agent install
one-liner, it lets a brand-new host register itself into the fleet and start
pulling config — no manual instance entry required. See
[Connect a Vector instance](../guides/connect-an-instance.md) and
[The VortexFlow agent](../reference/agent.md).

## Fleet-scoped vs. global

VortexFlow's navigation reflects the fleet model. Most screens are **fleet-scoped**
— they act on the fleet currently selected in the sidebar:

- Health, Catalog, Transforms, Flow, Live Tap

A few are **global**:

- Fleets (where you create and manage fleets), Instances, Settings

When you're building a pipeline or reading a dashboard, always check which fleet
is selected — that's the context you're operating in.

## Related

- [Instances & Agents](instances-and-agents.md) — what a fleet is made of.
- [Render, Deploy & Rollout](deploy-and-rollout.md) — how a fleet becomes config on every host.
- [Deploy to a fleet](../guides/deploy-to-a-fleet.md) — the hands-on guide.
