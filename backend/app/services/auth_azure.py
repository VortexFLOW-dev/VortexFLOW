# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Azure Entra ID (Azure AD) OIDC authentication service.

Kept as a named provider because:
  - Tenant-ID-based discovery is simpler to configure than a raw discovery_url
  - Future integration with Microsoft Graph for group sync / MFA claim verification
  - Most enterprises know it as "Azure SSO" — explicit UX is clearer than Generic OIDC

Flow:
  1. build_auth_url()  → redirect user to Microsoft login
  2. exchange_code()   → MSAL token exchange
  3. get_user_info()   → Microsoft Graph /me
  4. get_user_groups() → Microsoft Graph /memberOf (for role mapping)
  5. resolve_role()    → group object IDs → VortexFlow role slug
"""

from __future__ import annotations

from dataclasses import dataclass
import httpx

from app.core.config import AzureConfig


@dataclass
class AzureAuthResult:
    username: str
    email: str
    display_name: str
    role: str
    external_id: str  # Azure user object ID (sub)


class AzureAuthError(Exception):
    """Raised when Azure OIDC flow fails."""


def _resolve_role(group_ids: list[str], cfg: AzureConfig) -> str:
    """Resolve a VortexFlow role from a list of Azure group object IDs."""
    # New-style role_mappings (list of RoleMappingEntry)
    group_ids_lower = {g.lower() for g in group_ids}
    for mapping in cfg.role_mappings:
        target = (mapping.group_id or mapping.group or "").lower()
        if target and target in group_ids_lower:
            return mapping.role
    # Legacy flat dict mapping (group_role_mapping)
    if cfg.group_role_mapping:
        for gid, role in cfg.group_role_mapping.items():
            if gid.lower() in group_ids_lower:
                return role
    return cfg.default_role


def build_auth_url(cfg: AzureConfig, state: str) -> str:
    """Return the Microsoft authorization URL to redirect the user to."""
    if not cfg.enabled:
        raise AzureAuthError("Azure provider is not enabled")
    if not cfg.tenant_id or not cfg.client_id:
        raise AzureAuthError("Azure tenant_id and client_id must be configured")
    return (
        f"https://login.microsoftonline.com/{cfg.tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={cfg.client_id}"
        f"&response_type=code"
        f"&redirect_uri={cfg.redirect_uri}"
        f"&scope=openid+profile+email+User.Read+GroupMember.Read.All"
        f"&state={state}"
    )


async def exchange_code(cfg: AzureConfig, code: str) -> dict:
    """Exchange an authorization code for Azure tokens using MSAL."""
    try:
        import msal
    except ImportError:
        raise AzureAuthError("msal package is not installed")

    app = msal.ConfidentialClientApplication(
        cfg.client_id,
        authority=f"https://login.microsoftonline.com/{cfg.tenant_id}",
        client_credential=cfg.client_secret,
    )
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=["User.Read", "GroupMember.Read.All"],
        redirect_uri=cfg.redirect_uri,
    )
    if "error" in result:
        raise AzureAuthError(
            f"Token exchange failed: {result.get('error_description', result['error'])}"
        )
    return result


async def get_user_info(access_token: str) -> dict:
    """Fetch the user profile from Microsoft Graph /me."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    if r.status_code != 200:
        raise AzureAuthError(f"Graph /me failed: {r.status_code}")
    return r.json()


async def get_user_groups(access_token: str) -> list[str]:
    """Return a list of Azure group object IDs the user belongs to."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://graph.microsoft.com/v1.0/me/memberOf?$select=id",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    if r.status_code != 200:
        return []
    data = r.json()
    return [g.get("id", "") for g in data.get("value", []) if g.get("id")]


async def authenticate(cfg: AzureConfig, code: str) -> AzureAuthResult:
    """Full Azure OIDC flow: code → tokens → user info → role → result."""
    tokens = await exchange_code(cfg, code)
    access_token = tokens.get("access_token", "")
    user_info = await get_user_info(access_token)
    groups = await get_user_groups(access_token)

    email = user_info.get("mail") or user_info.get("userPrincipalName", "")
    display_name = user_info.get("displayName", "")
    sub = user_info.get("id", "")
    username = email.split("@")[0].replace(".", "_").lower() if email else sub

    role = _resolve_role(groups, cfg)

    return AzureAuthResult(
        username=username,
        email=email,
        display_name=display_name,
        role=role,
        external_id=sub,
    )
