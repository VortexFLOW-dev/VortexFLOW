# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
LDAP / Active Directory authentication service.

Flow:
  1. Bind to the directory with the service-account DN (bind_dn / bind_password)
  2. Search for the user entry matching user_filter (default: sAMAccountName)
  3. Re-bind as the found user to verify their password
  4. (optional) Query group membership and resolve a VortexFlow role
  5. Return an AuthResult ready for JWT issuance
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.config import LDAPConfig


@dataclass
class LDAPAuthResult:
    username: str
    email: str
    display_name: str
    role: str
    external_id: str  # LDAP distinguished name of the user entry
    # For SsoResult compatibility (shared jit_upsert): groups are the user's
    # group DNs; email_verified is N/A for directory auth (the directory is
    # authoritative for the address), so None — never an explicit False.
    groups: list[str]
    email_verified: bool | None = None


class LDAPAuthError(Exception):
    """Raised when LDAP authentication fails for any reason."""


def _resolve_role(group_dns: list[str], cfg: LDAPConfig) -> str:
    """Map LDAP group DNs to a VortexFlow role using the role_mappings config."""
    group_dns_lower = {g.lower() for g in group_dns}
    for mapping in cfg.role_mappings:
        target = (mapping.group or "").lower()
        if target and target in group_dns_lower:
            return mapping.role
    return cfg.default_role


def _get_groups(conn, user_dn: str, cfg: LDAPConfig) -> list[str]:
    """Return the DNs of the groups the user is a member of.

    Uses each matched entry's own DN (``entry_dn``), which works for both
    OpenLDAP (no ``distinguishedName`` attribute) and Active Directory.
    """
    if not cfg.group_base_dn:
        return []
    from ldap3.utils.conv import escape_filter_chars

    # A DN legitimately contains filter metacharacters (e.g. parens in a CN),
    # so escape it before substituting into the group filter.
    group_filter = cfg.group_filter.replace("{user_dn}", escape_filter_chars(user_dn))
    conn.search(
        search_base=cfg.group_base_dn,
        search_filter=group_filter,
        attributes=[],
    )
    return [str(entry.entry_dn) for entry in conn.entries]


async def authenticate(username: str, password: str, cfg: LDAPConfig) -> LDAPAuthResult:
    """
    Authenticate a user against LDAP/AD.  Runs the blocking ldap3 calls in a
    thread-pool executor so the event loop is not blocked.
    """
    if not cfg.enabled:
        raise LDAPAuthError("LDAP provider is not enabled")
    if not cfg.host:
        raise LDAPAuthError("LDAP host is not configured")
    # Reject empty credentials BEFORE any bind. An empty password makes most LDAP
    # servers perform an unauthenticated/anonymous bind that *succeeds* — the
    # classic LDAP auth-bypass. Never let a blank password reach a bind.
    if not username or not password:
        raise LDAPAuthError("Username and password are required")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_authenticate, username, password, cfg)


def _sync_authenticate(username: str, password: str, cfg: LDAPConfig) -> LDAPAuthResult:
    try:
        from ldap3 import Server, Connection, ALL, SUBTREE, Tls
        from ldap3.utils.conv import escape_filter_chars
        import ssl
    except ImportError:
        raise LDAPAuthError("ldap3 package is not installed")

    # ── Build server object ────────────────────────────────────────────────────
    tls_config = None
    if cfg.use_ssl or cfg.starttls:
        tls_config = Tls(validate=ssl.CERT_REQUIRED)

    server = Server(
        cfg.host, port=cfg.port, use_ssl=cfg.use_ssl, tls=tls_config, get_info=ALL
    )

    # ── Service-account bind ───────────────────────────────────────────────────
    try:
        svc_conn = Connection(
            server, user=cfg.bind_dn, password=cfg.bind_password, auto_bind=True
        )
    except Exception as exc:
        raise LDAPAuthError(f"LDAP service-account bind failed: {exc}") from exc

    if cfg.starttls:
        svc_conn.start_tls()

    # ── Find user entry ────────────────────────────────────────────────────────
    # Escape LDAP filter metacharacters in the submitted login so a value like
    # `*)(uid=*` can't alter the filter (defense-in-depth; the flow also rejects
    # >1 match and still requires a successful password bind as the found DN).
    user_filter = cfg.user_filter.replace("{username}", escape_filter_chars(username))
    attrs = ["distinguishedName", cfg.email_attr, cfg.display_name_attr]
    svc_conn.search(
        search_base=cfg.base_dn,
        search_filter=user_filter,
        search_scope=SUBTREE,
        attributes=attrs,
    )
    if not svc_conn.entries:
        raise LDAPAuthError("User not found in directory")
    if len(svc_conn.entries) > 1:
        raise LDAPAuthError("Multiple user entries matched — refine user_filter")

    entry = svc_conn.entries[0]
    user_dn = str(entry.entry_dn)

    # ── Re-bind as the user to verify password ────────────────────────────────
    try:
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
    except Exception:
        raise LDAPAuthError("Invalid credentials")
    user_conn.unbind()

    # ── Extract attributes ─────────────────────────────────────────────────────
    email = ""
    if hasattr(entry, cfg.email_attr):
        email = str(getattr(entry, cfg.email_attr)) or ""
    display_name = username
    if hasattr(entry, cfg.display_name_attr):
        display_name = str(getattr(entry, cfg.display_name_attr)) or username

    # ── Group membership → role ────────────────────────────────────────────────
    group_dns = _get_groups(svc_conn, user_dn, cfg)
    svc_conn.unbind()
    role = _resolve_role(group_dns, cfg)

    return LDAPAuthResult(
        username=username,
        email=email,
        display_name=display_name,
        role=role,
        external_id=user_dn,
        groups=group_dns,
    )
