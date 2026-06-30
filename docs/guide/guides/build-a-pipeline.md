# Build a pipeline in Flow

This guide builds a simple pipeline — a source, a VRL transform, and a sink — on
a fleet's [Flow canvas](../concepts/pipelines-and-flow.md). It assumes you have a
fleet with at least one connected instance.

## 1. Select the fleet

Pick the target fleet in the sidebar. Flow, like most screens, is
[fleet-scoped](../concepts/fleets.md#fleet-scoped-vs-global) — you're editing the
selected fleet's topology.

## 2. Add a source

1. Open **Flow** and click **+ Source**.
2. Choose a source type from the [catalog](../concepts/pipelines-and-flow.md#the-catalog)
   (for example `kubernetes_logs`, `journald`, or `syslog`).
3. Fill in the guided form. The form is generated from Vector's schema, so the
   fields match the component's real options.

The source appears as a teal node on the canvas.

## 3. Add a transform

1. Click **+ Transform** and choose a remap stage.
2. In the [VRL editor](../concepts/transforms-and-vrl.md), write your remap — for
   example parse a field, drop noise, or normalize a timestamp.
3. Paste a **sample event** into the preview to see the transformed output
   immediately. Iterate until it's right.
4. Optionally save the transform to the **library** to reuse it elsewhere.

## 4. Add a sink

1. Click **+ Source**'s sink equivalent / add a sink from the catalog (for
   example `victorialogs`, `elasticsearch`, or `aws_s3`).
2. Fill in the destination details. Reliability options (buffering,
   acknowledgements, health checks) are grouped under advanced settings.

## 5. Connect the nodes

Draw edges to define the flow: **source → transform → sink**. The connections are
the pipeline — an unconnected node won't appear in the rendered data path.

## 6. Preview the rendered config

Open the fleet's **Config** view to see the exact Vector YAML your topology
renders to. This is standard Vector config — no proprietary fields.

## 7. Deploy

When it looks right, [deploy to the fleet](deploy-to-a-fleet.md). VortexFlow
validates the config and publishes it to every member.

## Tips

- Use [Live Tap](live-tap.md) on the source and the transform to confirm data is
  shaped the way you expect, end to end.
- Disconnect a node (rather than deleting it) to temporarily take it out of the
  flow while keeping its configuration.
