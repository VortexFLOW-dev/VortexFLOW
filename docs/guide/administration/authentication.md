# Authentication & SSO

> **Status (pre-1.0):** **Local accounts, RBAC, and brute-force lockout are fully
> working.** The **SSO methods below (Entra / OIDC / SAML / LDAP) are in active
> development and not yet functional** — the settings forms exist, but the login
> flow is still being built. Use local accounts for now. This page documents the
> intended SSO model.

VortexFlow supports local accounts and four enterprise SSO methods, all
config-driven and active simultaneously. Sign-in settings live under
**Settings → Authentication**.

## Methods

| Method | Notes |
| --- | --- |
| **Local** | Username/password, hashed with bcrypt. Always available as a break-glass, even when SSO is on. |
| **Azure Entra ID** | OIDC via Microsoft's identity platform. |
| **Generic OIDC** | Any OIDC provider — Google, Okta, Auth0, Keycloak, … |
| **SAML 2.0** | Enterprise IdPs — ADFS, Ping, Shibboleth, and others. |
| **LDAP / AD** | Directory authentication for self-hosted environments. |

Enabled providers render as buttons on the login page; LDAP is handled
transparently through the local login form.

## JIT provisioning & group mapping

All SSO providers support **just-in-time provisioning** — a user that
authenticates successfully is created on first login, no manual pre-creation
needed. You can map **IdP groups to VortexFlow [roles](rbac.md)** per provider,
so directory membership drives access.

## Configuration source

Authentication configuration is stored in the database and takes precedence over
environment-variable fallbacks. This means you can configure SSO through the UI
without redeploying, and the settings persist. SSO buttons appear only for
providers that are enabled.

## Break-glass recovery

Local login is never fully disabled. In addition, an **admin recovery token** is
printed to the backend logs at startup; visiting `/recovery` with that token lets
you regain administrator access if SSO is misconfigured or an IdP is unreachable.
This is the same flow used to create the [first admin](../getting-started/installation.md#first-admin)
on a new install.

## Hardening

- **Brute-force lockout** — repeated failed logins lock an account for a cooldown
  (Redis-backed).
- **IP allowlisting** — restrict where sign-in is permitted.
- Use TLS in front of VortexFlow (see [TLS & Certificates](tls-certificates.md))
  so credentials and tokens are never sent in the clear.

## Related

- [Roles & RBAC](rbac.md) — what each role can do.
