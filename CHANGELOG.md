# Changelog

All notable changes to VortexFlow are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/) from
its first release.

## [Unreleased]

VortexFlow is pre-1.0 and under active development; this section tracks work
toward the first public release.

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

[Unreleased]: https://github.com/VortexFLOW-dev/VortexFLOW/commits/main
