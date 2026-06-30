# Connect a Vector instance

There are two ways to bring a Vector instance under VortexFlow management, by
[push mode](../concepts/instances-and-agents.md#config-push-modes). Pick the one
that matches where the instance runs.

## Option A — Agent mode (recommended for remote hosts)

Best when the Vector host is remote, behind NAT, or anything you'd rather not
reach inbound. A small agent runs on the host and **pulls** config.

1. In **Fleets**, open the fleet you want the host to join (or create one).
2. Copy the fleet's **agent install** one-liner. It embeds the fleet ID and a
   reusable bootstrap token:

   ```bash
   curl -sL https://<your-vortexflow>/install/fleet/<fleet-id>?token=<token> | sudo bash
   ```

3. Run it on the Vector host. The installer lays down the agent binary, a systemd
   unit, and a root-owned environment file, then starts the agent.
4. The agent registers itself, appears as a new instance in the fleet, and begins
   pulling config on its next poll.

See [The VortexFlow agent](../reference/agent.md) for what the installer does and
how to operate the agent.

## Option B — Local mode (co-located Vector)

Best when VortexFlow can write directly to a directory the Vector process
watches — for example a Vector in the same Docker stack on a shared volume.

1. Go to **Instances → Add instance**.
2. Fill in:
   - **Label** — a name for the host.
   - **Vector API URL** — e.g. `http://vector-host:8686` (used for health and live topology).
   - **Config push mode** — _Local_.
   - **Config directory** — the path VortexFlow writes the rendered config to.
3. Assign the instance to a [fleet](../concepts/fleets.md).
4. On the next [deploy](deploy-to-a-fleet.md), VortexFlow writes the fleet's
   rendered config to that directory and Vector (running with `--watch-config`)
   reloads.

## Verify

Whichever mode you used, the instance should appear under its fleet with:

- a **status dot** (green when healthy),
- its **Vector version**, and
- live **throughput** once data is flowing (visible on **Health**).

If it doesn't go healthy, check that VortexFlow can reach the instance's Vector
API URL, and for agent mode check the agent logs on the host
(`journalctl -u vortexflow-agent`).

## Next

- [Build a pipeline in Flow](build-a-pipeline.md)
- [Deploy to a fleet](deploy-to-a-fleet.md)
