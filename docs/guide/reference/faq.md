# FAQ

## Is VortexFlow really free and open source?

Yes — free, self-hosted, and licensed under [MPL 2.0](https://www.mozilla.org/MPL/2.0/),
the same license as Vector. No per-GB pricing, no license check, no telemetry.

## Does my data flow through VortexFlow?

No. VortexFlow is a **control plane** — it manages configuration. Your events
flow through **Vector**, never through VortexFlow. If VortexFlow is down, your
pipelines keep running. See [Architecture](architecture.md).

## Am I locked in if I adopt it?

No. Everything VortexFlow writes is **standard Vector YAML** — no proprietary
fields or wrappers. Stop using VortexFlow and your Vector config keeps running
untouched.

## Do I have to install an agent on every host?

No. Hosts VortexFlow can write to directly can run in
[local mode](../concepts/instances-and-agents.md#local-mode). The
[agent](agent.md) is for remote/distributed hosts where a pull model is better.

## Can a bad config take down my fleet?

The system is designed to prevent that. Every deploy is gated by a server-side
`vector validate` and a port-collision lint, and agent-mode hosts validate the
config **again locally** before reloading — refusing to apply anything that
doesn't pass, and keeping the last good config if it doesn't. See
[Render, Deploy & Rollout](../concepts/deploy-and-rollout.md).

## Can I upgrade Vector on some fleets but not others?

Yes. Pin a desired Vector version per [fleet](../concepts/fleets.md) and roll
upgrades out one fleet at a time. See
[Staged version rollout](../guides/version-rollout.md).

## Does VortexFlow do log search or dashboards on my data?

No. It manages the pipeline, not the data flowing through it. Use a log backend
for search and Grafana for dashboards on your data. VortexFlow's dashboards are
about **pipeline health** (throughput, errors, rollout), not your event content.

## Which Vector interfaces does it use?

Vector's configuration (YAML), Vector's GraphQL API (live topology and event
taps, default port 8686), Vector's internal metrics (health), and
`vector validate` (the pre-deploy gate). Because the contract is Vector's own,
VortexFlow stays accurate as Vector evolves.

## Where do I configure SSO, TLS, and notifications?

Under **Settings** — see [Authentication](../administration/authentication.md),
[TLS & Certificates](../administration/tls-certificates.md), and
[Notifications](../administration/notifications.md).

## How do I recover admin access if SSO breaks?

Local login is never disabled, and an admin recovery token is printed to the
backend logs at startup (`/recovery`). See
[Authentication → break-glass](../administration/authentication.md#break-glass-recovery).
