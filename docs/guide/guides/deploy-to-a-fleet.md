# Deploy to a fleet

Deploying renders a [fleet's](../concepts/fleets.md) pipeline into one validated
Vector config and publishes it to every member instance. For the full mechanics,
see [Render, Deploy & Rollout](../concepts/deploy-and-rollout.md); this is the
hands-on version.

## 1. Preview the config

With the fleet selected, open its **Config** view. VortexFlow renders the whole
topology to Vector YAML and shows it to you. Read it — what you see is exactly
what Vector will run.

## 2. Deploy

Click **Deploy**. VortexFlow first runs the [pre-deploy gate](../concepts/deploy-and-rollout.md#validate--the-pre-deploy-gate):

- **`vector validate`** against the rendered config, and
- a **port/address collision lint**.

If either fails, the deploy is **blocked** and you'll see the error — fix it and
try again. Nothing is shipped until both pass.

## 3. Watch the rollout

On a successful deploy, the fleet's [generation](../concepts/fleets.md#generation)
advances and the config is published:

- **Local-mode** instances get the file written immediately.
- **Agent-mode** instances pull the new generation on their next poll, validate
  it locally, and reload Vector.

Watch the fleet converge — members move onto the new generation until you reach
`N/N`. A member that lags is simply slow or offline; it converges when it
returns. A member that reports a validation or reload failure raises an alert and
keeps running its last good config.

## 4. If something's wrong

- **A host won't converge.** Check it's online and (agent mode) that the agent is
  polling — `journalctl -u vortexflow-agent` on the host.
- **A deploy failed validation.** The error names the problem; common causes are
  an invalid sink option or two sources bound to the same port.
- **You need to undo a change.** Use a pipeline's **history** to roll back to a
  previous version, then deploy again. The rollback is itself recorded.

## Related

- [Render, Deploy & Rollout](../concepts/deploy-and-rollout.md)
- [Staged version rollout](version-rollout.md) — upgrading Vector itself, separately from config.
