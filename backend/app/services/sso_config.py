# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Load typed SSO provider configs from the ``system_settings`` table.

The Settings UI persists provider config as JSON under keys ``sso_oidc`` etc.
(see ``app.api.v1.settings``). The auth services consume the typed dataclasses
from ``app.core.config``. This module bridges the two: read the JSON, build the
dataclass. Env-var fallbacks let a deployment that predates the Settings UI keep
working.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import (
    LDAPConfig,
    OIDCConfig,
    RoleMappingEntry,
    SAMLConfig,
    settings,
)
from app.models.system_setting import SystemSetting
from app.services import cert_crypto


def _secret(data: dict, field: str, env_fallback: str | None) -> str:
    """Resolve an SSO secret from DB settings, then env.

    The Settings API stores the secret Fernet-encrypted under
    ``<field>_encrypted``; installs that predate at-rest encryption may still
    hold a legacy plaintext ``<field>`` value. Prefer the ciphertext, fall back
    to legacy plaintext, then the env var. A ciphertext that won't decrypt (the
    ``VORTEXFLOW_SECRET_KEY`` was rotated) resolves to empty so auth fails closed
    rather than binding with a wrong secret."""
    enc = data.get(f"{field}_encrypted")
    if enc:
        try:
            return cert_crypto.decrypt(enc, settings.secret_key)
        except Exception:
            return ""
    legacy = data.get(field)
    if legacy:
        return str(legacy)
    return env_fallback or ""


async def _load_json(key: str, db: AsyncSession) -> dict:
    row = await db.get(SystemSetting, key)
    if row is None:
        return {}
    try:
        data = json.loads(row.value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _role_mappings(raw: object) -> list[RoleMappingEntry]:
    out: list[RoleMappingEntry] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        out.append(
            RoleMappingEntry(
                role=role,
                group=(str(item.get("group")).strip() or None)
                if item.get("group")
                else None,
                group_id=(str(item.get("group_id")).strip() or None)
                if item.get("group_id")
                else None,
            )
        )
    return out


async def load_ldap_config(db: AsyncSession) -> LDAPConfig:
    """Build the LDAP runtime config from DB settings, falling back to env vars.

    The Settings UI stores a single ``url`` (ldap://host:389 or ldaps://host:636);
    we parse it into host/port/use_ssl for ldap3.
    """
    data = await _load_json("sso_ldap", db)

    url = str(data.get("url") or settings.ldap_url or "")
    host, port, use_ssl = "", 389, False
    if url:
        parsed = urlparse(url if "://" in url else f"ldap://{url}")
        host = parsed.hostname or ""
        use_ssl = parsed.scheme == "ldaps"
        port = parsed.port or (636 if use_ssl else 389)

    enabled = bool(data.get("enabled", False)) or bool(url)

    return LDAPConfig(
        enabled=enabled,
        host=host,
        port=port,
        use_ssl=use_ssl,
        starttls=bool(data.get("starttls", False)),
        bind_dn=str(data.get("bind_dn") or settings.ldap_bind_dn or ""),
        bind_password=_secret(data, "bind_password", settings.ldap_bind_password),
        base_dn=str(data.get("base_dn") or settings.ldap_base_dn or ""),
        user_filter=str(data.get("user_filter") or settings.ldap_user_filter),
        email_attr=str(data.get("email_attr") or "mail"),
        display_name_attr=str(data.get("display_name_attr") or "displayName"),
        group_base_dn=str(
            data.get("group_base_dn") or settings.ldap_group_base_dn or ""
        ),
        group_filter=str(data.get("group_filter") or "(member={user_dn})"),
        role_mappings=_role_mappings(data.get("role_mappings")),
        default_role=str(data.get("default_role") or "viewer"),
    )


async def load_saml_config(db: AsyncSession) -> SAMLConfig:
    """Build the SAML runtime config from DB settings.

    SP identifiers (entity id, ACS url) are derived from ``public_url`` so they
    match what the IdP POSTs back to (the ACS ``Destination`` must equal our
    self-url, which python3-saml validates). ``public_url`` is therefore required
    for SAML to work behind a reverse proxy.
    """
    data = await _load_json("sso_saml", db)

    base = (settings.public_url or "").rstrip("/")
    acs_url = f"{base}/api/v1/auth/saml/acs" if base else ""
    sp_entity_id = str(
        data.get("sp_entity_id")
        or settings.saml_sp_entity_id
        or (f"{base}/api/v1/auth/saml/metadata" if base else "")
    )

    enabled = bool(data.get("enabled", False)) or bool(
        data.get("idp_metadata_url") or data.get("idp_sso_url")
    )

    return SAMLConfig(
        enabled=enabled,
        sp_entity_id=sp_entity_id,
        acs_url=acs_url,
        name_id_format=str(
            data.get("name_id_format")
            or "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
        ),
        idp_metadata_url=str(
            data.get("idp_metadata_url") or settings.saml_idp_metadata_url or ""
        ),
        idp_entity_id=str(
            data.get("idp_entity_id") or settings.saml_idp_entity_id or ""
        ),
        idp_sso_url=str(data.get("idp_sso_url") or settings.saml_idp_sso_url or ""),
        idp_x509_cert=str(
            data.get("idp_x509_cert") or settings.saml_idp_x509_cert or ""
        ),
        attr_username=str(data.get("attr_username") or "username"),
        attr_email=str(data.get("attr_email") or "email"),
        attr_display_name=str(data.get("attr_display_name") or "displayName"),
        attr_groups=str(data.get("attr_groups") or "groups"),
        role_mappings=_role_mappings(data.get("role_mappings")),
        default_role=str(data.get("default_role") or "viewer"),
    )


async def load_azure_config(db: AsyncSession) -> OIDCConfig:
    """Build an OIDC runtime config for Azure Entra ID.

    Azure's v2.0 endpoint is fully OIDC-compliant, so Azure reuses the generic
    OIDC auth-code+JWKS flow — we just derive the issuer from the tenant id and
    map role_mappings by Azure group *object id*. (Group object ids appear in the
    ``groups`` claim only when the app registration sets groupMembershipClaims;
    otherwise users fall through to default_role. Graph-based group-name
    resolution + >200-group overage handling is a later enhancement.)
    """
    data = await _load_json("sso_azure", db)

    tenant_id = str(data.get("tenant_id") or settings.azure_tenant_id or "")
    client_id = str(data.get("client_id") or settings.azure_client_id or "")
    client_secret = _secret(data, "client_secret", settings.azure_client_secret)
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0" if tenant_id else ""
    enabled = bool(data.get("enabled", False)) or bool(tenant_id and client_id)

    return OIDCConfig(
        enabled=enabled,
        display_name="Microsoft",
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=str(data.get("redirect_uri") or ""),
        scopes=["openid", "profile", "email"],
        email_claim="email",
        username_claim="preferred_username",
        groups_claim="groups",
        role_mappings=_role_mappings(data.get("role_mappings")),
        default_role=str(data.get("default_role") or "viewer"),
    )


async def load_oidc_config(db: AsyncSession) -> OIDCConfig:
    """Build the OIDC runtime config from DB settings, falling back to env vars."""
    data = await _load_json("sso_oidc", db)

    issuer = str(data.get("issuer") or settings.oidc_issuer or "")
    client_id = str(data.get("client_id") or settings.oidc_client_id or "")
    client_secret = _secret(data, "client_secret", settings.oidc_client_secret)

    scopes_raw = data.get("scopes")
    if isinstance(scopes_raw, list) and scopes_raw:
        scopes = [str(s) for s in scopes_raw]
    else:
        scopes = ["openid", "profile", "email"]
    # openid is mandatory for an ID token to be returned
    if "openid" not in scopes:
        scopes = ["openid", *scopes]

    enabled = bool(data.get("enabled", False)) or bool(issuer and client_id)

    return OIDCConfig(
        enabled=enabled,
        display_name=str(data.get("display_name") or settings.oidc_display_name),
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=str(data.get("redirect_uri") or ""),
        scopes=scopes,
        email_claim=str(data.get("email_claim") or "email"),
        username_claim=str(data.get("username_claim") or "preferred_username"),
        groups_claim=str(data.get("groups_claim") or "groups"),
        role_mappings=_role_mappings(data.get("role_mappings")),
        default_role=str(data.get("default_role") or "viewer"),
    )
