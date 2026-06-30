# Staged version rollout

Upgrading the **Vector binary** across a fleet is separate from deploying config.
No production setup wants every host to jump versions at once, so VortexFlow lets
you stage Vector upgrades **one fleet at a time**, with drift surfaced the whole
way.

> This is the "Vector version" plane. For shipping pipeline changes, see
> [Deploy to a fleet](deploy-to-a-fleet.md).

## How it works

- There is a **global default** Vector version.
- Each [fleet](../concepts/fleets.md) can pin its own **desired Vector version**,
  overriding the global default.
- Each instance reports the Vector version actually **installed** on its host.
- VortexFlow compares installed vs. desired and flags **drift**.

In agent mode, the agent reconciles the installed binary toward the fleet's
desired version; otherwise drift is reported so you can act on it.

## Roll out to one fleet

1. Decide the target version and which fleet goes first (often a canary or a
   staging fleet).
2. On that fleet, set its **desired Vector version** to the target.
3. The fleet's members now show as **drifted** until they reach the target
   version; watch them converge.
4. Verify health on the upgraded fleet — throughput steady, no new errors.
5. Repeat for the next fleet. Promote the version to the **global default** once
   you're confident, so new and unpinned fleets pick it up too.

## Reading drift

- A **warning** on an instance that its Vector version differs from what its
  fleet desires is the signal of an in-progress (or stalled) rollout.
- Drift that doesn't clear means a host hasn't upgraded — check the host and, in
  agent mode, the agent logs.

## Why staged

Staging gives you blast-radius control: a bad Vector release shows up on the
first fleet you upgrade, not across your whole estate. Combined with the
[pre-deploy config gate](../concepts/deploy-and-rollout.md#validate--the-pre-deploy-gate)
and agent-side validate-then-reload, version and config changes both roll out
safely.

## Related

- [Fleets → Per-fleet Vector version](../concepts/fleets.md#per-fleet-vector-version)
- [Instances & Agents → Version drift](../concepts/instances-and-agents.md#version-drift)
