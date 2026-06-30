# Roles & RBAC

VortexFlow ships three built-in roles. Every user — local or
[SSO](authentication.md) — has exactly one role, which can be assigned directly
or mapped from an IdP group.

## The roles

| Role | Can do |
| --- | --- |
| **Admin** | Everything — manage users, instances, fleets, all pipelines, and system settings. |
| **Editor** | Create, edit, and delete pipelines and VRL transforms. Cannot manage users or instances. |
| **Viewer** | Read-only — view pipelines, health, and the transform library. |

## Choosing roles

- Give **Viewer** to anyone who needs visibility into pipeline health but
  shouldn't change config — on-call responders, stakeholders, auditors.
- Give **Editor** to the people who build and maintain pipelines.
- Keep **Admin** to the few who manage the platform itself — users, instances,
  fleets, SSO, TLS, and settings.

## Assigning a role

- **Directly** — under **Settings → Users**, set a user's role.
- **From SSO** — map IdP groups to roles per provider so directory membership
  drives access automatically (see
  [Authentication → JIT & group mapping](authentication.md#jit-provisioning--group-mapping)).

## Notes

- Local login and the [recovery break-glass](authentication.md#break-glass-recovery)
  always retain an administrator path, so you can't lock yourself out by
  misconfiguring SSO group mappings.
- Finer-grained, instance- or fleet-scoped permissions (e.g. Editor on staging,
  Viewer on prod) and custom roles are _planned_ beyond the initial three.
