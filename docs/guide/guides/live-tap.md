# Tap live events

**Live Tap** lets you sample the real events flowing through any node in a
running pipeline — without adding a debug sink or changing config. It reads
straight from Vector's tap API, with no retention: events stream to your screen
and are gone.

## When to use it

- Confirm a source is actually receiving data.
- See exactly what a [transform](../concepts/transforms-and-vrl.md) produces,
  in production, on real events.
- Debug a routing condition by watching which branch events take.

## From Live Tap

1. Select the [fleet](../concepts/fleets.md) in the sidebar.
2. Open **Live Tap**.
3. Choose the **component** to tap from the dropdown (sources and transforms are
   tappable).
4. Start the tap. Live events stream in as Vector emits them.

## From the Flow canvas

You can also tap straight from the topology:

1. In **Flow**, click a source or transform node.
2. Choose **Tap this node**.
3. You land in Live Tap with that component pre-selected.

## Compare a transform's before & after

When the component you select is a **transform**, a **Compare before / after**
toggle appears. Turn it on and Live Tap opens two panes side by side:

- **Before** — the events feeding the transform (its input).
- **After** — the events the transform emits (its output).

This is the fastest way to see exactly what your VRL did to each event — a field
added, a value rewritten, an event dropped. It's the equivalent of Cribl's
capture/diff, on live production data, with no debug sink.

## Filter and inspect fields

Both the single and compare views support:

- **Filter** — type a substring to show only matching events. It filters the
  view live (the underlying stream keeps running); the header shows `shown/total`.
- **Fields** — toggle the **Fields** panel to see the schema VortexFlow inferred
  from the sample: each field name, its type(s), and what percentage of events
  carried it. In compare mode each pane has its own field list, so a field a
  transform adds (or removes) shows up on only one side.
- **Pause / Stop / Clear / Copy** — freeze the stream or copy the (filtered) sample.

## What you see

Each tapped event is shown as it flows through the chosen component — for a
transform, that's the **output** of the remap, so you're seeing the effect of
your logic on live data. Because it's a sample with no retention, Live Tap is
safe to run against production: it doesn't store events or alter the pipeline.

## Notes & limits

- Tapping requires the instance's Vector API to be reachable by VortexFlow.
- A node must be **wired into the running config** to have events to tap — a
  freshly added, not-yet-deployed component won't show anything until you
  [deploy](deploy-to-a-fleet.md).
- Live Tap is for **sampling and debugging**, not bulk inspection or search —
  VortexFlow is not a log search tool.
