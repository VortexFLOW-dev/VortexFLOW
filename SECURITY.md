# Security Policy

We take the security of VortexFlow seriously. VortexFlow sits in the control
path for data pipelines and handles credentials, certificates, and agent tokens,
so we appreciate responsible disclosure.

## Reporting a vulnerability

**Please do not report security issues through public GitHub issues, discussions,
or pull requests.**

Instead, report privately through one of:

- **GitHub Security Advisories** — on this repository, go to the **Security** tab
  → **Report a vulnerability** (preferred; keeps the report private and tracked).
- **Email** — `security@vortexflow.dev`.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof of concept if you have one).
- Affected version / commit, and configuration relevant to the issue.

## What to expect

- We aim to acknowledge a report within **3 business days**.
- We'll keep you informed as we investigate, and coordinate a disclosure
  timeline with you. We ask that you give us a reasonable window to release a fix
  before any public disclosure.
- With your permission, we'll credit you in the release notes.

## Scope

In scope: the VortexFlow backend, frontend, the `vortexflow-agent`, and the
default Docker deployment. Out of scope: vulnerabilities in upstream
dependencies (report those upstream; we'll pick up the fix), and issues that
require an already-compromised host or pre-existing admin access.

## Supported versions

VortexFlow is pre-1.0. Until a 1.0 release, security fixes land on `main`; please
test against the latest `main` before reporting.
