# Privacy

VortexFlow is self-hosted software that you run on your own infrastructure.

## What VortexFlow collects

**Nothing.** VortexFlow does not phone home. It contains:

- No telemetry or usage analytics.
- No crash/error reporting to any external service.
- No license check, activation, or "call home" of any kind.
- No third-party trackers in the web UI.

VortexFlow makes outbound network connections **only** to the systems you
explicitly configure: your Vector instances, your VortexFlow agents, and the
identity provider you set up for SSO (if any). It never contacts the VortexFlow
project or its maintainers.

## What VortexFlow stores

All data stays in **your** PostgreSQL database and Redis instance. This includes
your users, roles, Vector instance definitions, pipeline/transform config,
audit log, and any credentials or certificates you add (sink credentials and
certificate private keys are encrypted at rest).

Because VortexFlow is self-hosted, you are the data controller for everything it
stores. Operating it in line with your own regulatory obligations (GDPR, etc.)
is your responsibility.

## Updates & dependencies

VortexFlow does not auto-update. You choose when to pull a new image or build.
Standard dependency-update tooling (e.g. Dependabot) runs in this repository for
development, not in your deployment.

## Questions

Privacy questions: open a discussion or issue. Suspected security issues: follow
`SECURITY.md` instead.
