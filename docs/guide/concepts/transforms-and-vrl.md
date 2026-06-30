# Transforms & VRL

Transforms are where events get reshaped — parsed, enriched, filtered,
normalized — on their way through a pipeline. In Vector, most transform logic is
written in **VRL** (Vector Remap Language), and VortexFlow gives VRL a proper
editor with a live preview and a reusable library.

## The VRL editor

VortexFlow embeds a full code editor for VRL with:

- **Syntax highlighting** tuned for VRL, in both dark and light themes.
- **A live preview**, two ways. Provide a sample input event, then:
  - **Validate** compile-checks and runs your remap using the **bundled Vector
    binary on the server** — *no live instance required*. It returns the transformed
    event, or Vector's own compiler diagnostic (e.g. `error[E105]: call to undefined
    function`) pointed right at the offending line. This is the fastest loop and works
    even before you've added a single instance.
  - **Run ▶** executes against a live Vector instance (via Vector's remap testing
    API) for the full end-to-end path.

This turns VRL authoring from "edit, deploy, hope" into a tight feedback loop.

## The transform library

A remap you write once is rarely needed only once. The **transform library**
lets you save a VRL transform (backed by the database) and reference it from
multiple pipelines, instead of copy-pasting the same snippet between five config
files and watching them drift apart.

- **Write once, reuse everywhere.** Reference a library transform from any fleet.
- **One source of truth.** Fix a transform in the library and every place that
  references it benefits.
- **Import & export.** Download a single transform as a `.vrl` file, or export the
  whole library as a portable `vrl-transforms` JSON pack — then import a `.vrl` file
  or a pack to bring transforms into another VortexFlow. Handy for sharing, backups,
  and moving logic between environments.

## How transforms join the pipeline

On a fleet, transforms exist as **stages** that wire into the
[Flow topology](pipelines-and-flow.md). A stage:

- takes its **inputs** from sources or from other stages, and
- feeds its output onward to routes or sinks,

producing a `source → remap → route → sink` graph. A stage can hold inline VRL or
reference a library transform. At render time, each stage becomes a Vector
`remap` transform in the deployed config — see
[Render, Deploy & Rollout](deploy-and-rollout.md).

## A note on VRL itself

VRL is Vector's expression-oriented language for working with events. A few
practical tips that come up constantly:

- VRL is **fallible** — operations that can fail (parsing, type coercion) must be
  handled, e.g. with the `??` coalescing operator or by capturing the error.
- Prefer the preview to catch mistakes early; many VRL errors (like unnecessary
  error coalescing) are reported at compile time and the preview surfaces them.
- Keep transforms small and composable; the library rewards single-purpose remaps
  you can combine.

For the language itself, Vector's [VRL reference](https://vector.dev/docs/reference/vrl/)
is the authoritative source — VortexFlow runs the same VRL engine Vector does.

## Related

- [Pipelines & Flow](pipelines-and-flow.md) — where transforms sit in the topology.
- [Build a pipeline in Flow](../guides/build-a-pipeline.md) — author a transform in context.
