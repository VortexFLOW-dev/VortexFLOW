# Changelog

All notable changes to VortexFlow are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/) from
its first release.

## [Unreleased]

### Changed
- Dependency updates: `redis` 8, `docker/metadata-action` v6, and routine
  frontend (monaco-editor, @xyflow/react, radix, eslint, postcss) + backend
  (asyncpg, anthropic, aiofiles) and base-image (nginx) bumps.

### Security
- **Agents are served only the last successfully-deployed config.** The agent
  config endpoint now returns an encrypted snapshot of the config from the last
  successful deploy (written after `vector validate` passes), never a live DB
  render — so an editor's un-deployed change can no longer reach a fleet host.
- **Restricted the public `/vm` proxy to the metrics write endpoint.** It
  previously reverse-proxied the entire VictoriaMetrics API to the front door,
  including read/export and the destructive `admin/tsdb/delete_series`.
- **Server-side session lifecycle.** Logout now revokes the access token,
  invalidates the refresh token, and ends the session; sessions enforce an idle
  timeout and an absolute cap; refresh-token replay fails closed; and the client
  IP is read via a trusted-proxy count so `X-Forwarded-For` can no longer be
  spoofed to defeat brute-force / IP-block counters.
- **SSO IdP secrets are encrypted at rest and never sent to the browser.** The
  OIDC/Azure `client_secret` and the LDAP `bind_password` are Fernet-encrypted
  in `system_settings` (were stored plaintext), masked on read, and preserved on
  write (mirrors the AI-key handling). A legacy plaintext value is migrated to
  ciphertext on the next save; a secret that won't decrypt after a key rotation
  fails closed.
- The one-time setup/recovery token is armed only on a fresh install or explicit
  opt-in, instead of being printed to the logs on every boot.
- SMTP STARTTLS now verifies the mail server's certificate.
- The install script verifies the downloaded agent binary against a per-arch
  sha256 embedded from the operator's authenticated session.
- A component's user-supplied `config` can no longer override the reserved
  `type` or `inputs` keys the renderer computes. A `config.type` would otherwise
  defeat the create-time component-type allowlist (a source could deploy as any
  sink type) and `config.inputs` could silently re-route a sink; both are now
  dropped with a render warning.
- Creating a personal access token now enforces the forced-password-change gate.
  A PAT inherits its owner's role, so a user required to rotate their password
  could previously mint one and use it to bypass the gate; token creation now
  returns 403 until the password is changed.
- Password policy is now centralized and enforces bcrypt's 72-byte input limit
  across every set path (change, admin create/reset, recovery). bcrypt hashes
  only the first 72 bytes, so a longer password was silently truncated — two
  different long passwords could authenticate each other. Such passwords are now
  rejected (byte-counted, so multi-byte characters count correctly), and
  `get_password_hash` refuses over-length input as a backstop.
- Login no longer leaks account existence through response timing. When there is
  no local password to verify (unknown email, an SSO/LDAP account, or an inactive
  account), the handler now performs one dummy bcrypt verify so the response time
  matches a real local-password check.
- The notification "send test" action no longer echoes raw connection errors.
  A raw SMTP/socket failure carries the target host and the refused/timeout/DNS
  distinction, which turned this admin action into an internal port-scan oracle;
  the email path now raises a host/errno-free error (like the webhook path) and
  the endpoint surfaces only sanitized messages.
- Instance `api_url` now rejects loopback / link-local addresses (SSRF) on both
  create and update — the server makes outbound calls to it, and the update path
  previously had no validation at all. The check is shared with the agent-
  registration validator (loopback + `169.254.0.0/16` cloud-metadata + IPv6
  link-local blocked; RFC1918 still allowed).
- `vector validate` output shown to editors (the fleet validate endpoint and the
  pre-deploy 409) is now scrubbed of any inlined secret values, so a validator
  error that echoes a config value can't leak a decrypted credential back to the
  browser.
- A credential-named component field with a non-string value (e.g. a numeric or
  boolean `password`/`api_key`) is now encrypted at rest like any other secret;
  previously only string secrets were extracted, so a non-string value fell
  through to plaintext `config_json` and showed in config previews / API reads.
- The root agent now confines every server-supplied cert-file write to the
  managed component-certs directory (rejecting absolute paths outside it and
  `..` traversal), so a compromised or malicious control plane can no longer
  turn the deploy pull into an arbitrary root file write on a fleet host. Adds a
  CI job that vets, builds, and tests the Go agent (previously untested in CI).
- The fleet bootstrap token is now passed in an `X-Bootstrap-Token` request
  header instead of a URL query string, so it no longer lands in nginx / reverse
  proxy access logs.
- The backend container runs as a non-root user.
- Agent-registration rate limiting keys on the real client IP (was the proxy's,
  i.e. one shared bucket for all agents).
- The rendered Vector config is now written `0600` (was `0644`) — on the deploy
  path it can embed decrypted secrets, so it must not be world-readable.
- Bounded the PEM-label regex to eliminate a polynomial-ReDoS on CA-chain input.
- Scoped GitHub Actions write permissions down to the job (top-level read-only).
- Pinned the previously-unpinned CI executables (gitleaks, license-checker) and
  held `cryptography` below 49 (msal caps it).

### Fixed
- External alerts (webhook/Slack/email) could be silently dropped when a
  dashboard poll observed a condition transition before the background worker;
  the dashboard read path now enqueues deliveries too.
- Metrics-driven events are no longer false-resolved (a spurious "all clear")
  while VictoriaMetrics is unreachable.
- Notification deliveries are claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so
  running multiple backend replicas no longer double-sends.
- The "add instance to fleet" dialog now lists instances (it read a field that
  didn't exist on the response).
- The cert-store key derivation is cached off the async event loop.

## [1.0.0] - 2026-06-30

First public release — a free, self-hosted control plane for Vector fleets:
build pipelines visually, render and deploy them across a fleet, and operate
them with staged version rollouts, pre-deploy validation, and live event taps.

### Added
- **Fleet manager & deploy engine** — group Vector instances into Fleets, render
  a fleet to one validated Vector config, and deploy it to every member.
- **Pull-based agents** (`vortexflow-agent`) with validate-then-reload and a
  one-liner bootstrap.
- **Staged per-fleet Vector version rollouts** with drift detection.
- **Source/sink catalog** generated from Vector's JSON schema.
- **AI VRL transform assistant** (opt-in, bring-your-own-LLM) — describe a
  transform and a sample event; the assistant writes VRL, compiles it with the
  bundled Vector binary, and self-repairs on error, so only validated VRL is
  returned (with before/after on the event). Self-hosted / no-phone-home:
  Anthropic, OpenAI, or a local OpenAI-compatible endpoint (Ollama, vLLM); the
  key is encrypted at rest with opt-in field redaction before egress.
- **Contract Drift Sentinel** — build-time CI checks that keep the catalog, the
  backend's accepted-type allowlist, the DB schema provisioner, and the pinned
  Vector version from silently drifting (`make sentinel`).
- **Live event tap** on any node.
- **Cert store ↔ component TLS wiring** — reference a stored certificate for a
  component's TLS; certs are delivered to local-mode hosts and to agents.
- User & operator **documentation** under `docs/guide/`.

### Changed
- Component credentials are now **encrypted at rest** and masked in all read
  paths; decrypted only at deploy.
- The first admin is created via a one-time **setup token** — no static default
  password is seeded on a real install (demo mode still seeds the documented
  account).

### Fixed
- The component picker offered Vector source/sink types the backend then rejected
  with `422` on create (~63 types). The backend's accepted-type list is now
  generated from the same Vector schema as the catalog (kind-aware), so the API
  accepts exactly what the picker shows — and a source-only type can no longer be
  created as a sink.

### Security
- Encrypt sink/source credentials at rest (Fernet); mask in API + config preview.
- Add nginx security headers (HSTS, CSP, `X-Content-Type-Options`,
  `X-Frame-Options`, Referrer-Policy, Permissions-Policy).
- Remove the unused `authlib` dependency and bump `python-multipart` /
  `cryptography` — backend dependency audit clean.

[Unreleased]: https://github.com/VortexFLOW-dev/VortexFLOW/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/VortexFLOW-dev/VortexFLOW/releases/tag/v1.0.0
