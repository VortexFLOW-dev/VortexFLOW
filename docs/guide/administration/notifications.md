# Notifications

VortexFlow can send alerts to external channels when something needs attention —
a host goes offline, a config reload fails, a certificate is about to expire.
Channels are managed by an administrator under **Settings → Notifications**.

## The event model

VortexFlow continuously detects conditions across your fleets and records them as
**events** with a severity. The same events drive the in-app notification center
(the bell in the sidebar) and any outbound channels you configure. Events
**auto-resolve** when the condition clears, so you also get an "all clear" when
appropriate.

Examples of conditions that raise events:

- An agent-mode instance hasn't checked in (offline).
- A config **validation** or **reload** failed on a host.
- An instance is **dropping events** (data loss — critical) or its **sink
  deliveries are failing** (warning). See
  [Monitor fleet health](../guides/monitor-fleet-health.md).
- An instance is running an unexpected Vector version
  ([drift](../concepts/instances-and-agents.md#version-drift)).
- A [certificate](tls-certificates.md) is nearing expiry.

## Channel types

| Type | Use |
| --- | --- |
| **Webhook** | POST events to any HTTP endpoint. |
| **Slack** | Post to a Slack channel via an incoming webhook. |
| **Microsoft Teams** | Post to a Teams channel. |
| **Email** | Send to one or more addresses. |

Channel secrets (webhook URLs, tokens) are **encrypted at rest**.

## Per-channel controls

- **Minimum severity** — only deliver events at or above a threshold, so a
  channel can be tuned for "critical only" vs. "everything."
- **Notify on resolve** — choose whether the channel also receives the "all
  clear" when a condition clears. The resolve notice is only sent if the original
  alert was actually delivered, so you won't get an orphaned "resolved" with no
  matching alert.
- **Test** — send a test message to confirm a channel is wired correctly before
  you rely on it.

## How delivery works

A background worker evaluates conditions and dispatches notifications on an
interval, independent of whether anyone has the UI open — so alerts fire even at
3 a.m. with no browser tab. Deliveries are de-duplicated and retried with backoff
if a channel is temporarily unreachable.

## Recommendations

- Start with one **critical-only** channel (e.g. Slack) so the signal stays high.
- Add a lower-severity channel later if you want fuller visibility.
- Always **Test** a new channel before depending on it.
