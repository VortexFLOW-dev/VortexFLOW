# Pipelines & Flow

A Vector pipeline is a directed graph: data enters through **sources**, passes
through **transforms** and **routes**, and leaves through **sinks**. VortexFlow
models this on a visual canvas called **Flow**, where each component is a node
and the connections between them are edges.

Components are [fleet-scoped](fleets.md): the sources, transforms, routes, and
sinks you define belong to the selected fleet, and together they render into that
fleet's Vector config.

## The component types

| Type | What it does | Color on the canvas |
| --- | --- | --- |
| **Source** | Brings data in (files, journald, kubernetes logs, syslog, HTTP, …) | teal |
| **Transform** | Reshapes events — most commonly a [VRL remap](transforms-and-vrl.md) | amber |
| **Route** | Branches the stream on conditions, fanning to different sinks | amber |
| **Sink** | Sends data out (VictoriaLogs, S3, Elasticsearch, Kafka, …) | sky blue |

The canvas legend uses **color, not shape**, to distinguish types, so node labels
stay readable.

## Flow: the canvas

Open **Flow** with a fleet selected to see and edit that fleet's topology:

- **Add** sources and transforms from the toolbar; pick concrete component types
  from the catalog.
- **Connect** nodes to define how events flow — an edge from a source to a remap
  to a sink _is_ the pipeline.
- **Tap** any node to sample the live events flowing through it
  ([Tap live events](../guides/live-tap.md)).

A component that exists but isn't connected to anything simply sits on the canvas
as an unwired node. It won't appear in the rendered config's data path until you
connect it — disconnecting a node is a safe way to take it out of the flow
without deleting it.

## The catalog

When you add a source or sink, you choose its type from the **catalog** and fill
in a guided form instead of memorizing Vector's config keys. The catalog's forms
are **generated from Vector's own JSON schema**, so they stay accurate as Vector
adds and changes components — there's no hand-maintained list to fall behind.

Common options are presented directly; advanced and reliability settings (buffers,
acknowledgements, health checks) are grouped so the simple case stays simple.

## Routes

Routing lets one stream branch to different destinations based on conditions
(VRL expressions). In VortexFlow, routes are edited alongside transforms rather
than as a separate page — a route is just another node that compiles down to a
Vector `route` transform, with each branch wired to its own sinks and an optional
passthrough for unmatched events.

## From canvas to config

The Flow canvas is an editor, not the runtime. Nothing on the canvas affects a
running Vector until you **deploy** the fleet, at which point VortexFlow renders
the whole topology into one Vector config and publishes it. The rendered output
is exactly the standard Vector YAML you'd have written by hand — see
[Render, Deploy & Rollout](deploy-and-rollout.md).

## Related

- [Transforms & VRL](transforms-and-vrl.md) — author the remap logic in your transforms.
- [Build a pipeline in Flow](../guides/build-a-pipeline.md) — the hands-on guide.
- [Render, Deploy & Rollout](deploy-and-rollout.md) — turn the canvas into running config.
