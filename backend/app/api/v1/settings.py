# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Settings API — read/write SSO provider configuration stored in system_settings.

Keys: sso_azure, sso_oidc, sso_saml, sso_ldap, general, tls
Values: JSON blobs with provider-specific fields.

Changes take effect on next restart (v1 limitation documented in UI).
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.database import get_db
from app.middleware.rbac import require_admin
from app.models.certificate import Certificate
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services import ai_client, ai_config, audit, cert_crypto
from app.services.redis_client import check_rate_limit
from app.services.secrets import MASK

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Pydantic models ──────────────────────────────────────────────────────────


class RoleMapping(BaseModel):
    """Map an IdP group (by name, or object-id for Azure) to a VortexFlow role."""

    group: str = ""  # group name / path; for Azure use group_id
    group_id: str = ""  # Azure group object id
    role: str = "viewer"


class AzureSettings(BaseModel):
    enabled: bool = False
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    # Azure emits group *object ids* in the groups claim (set
    # groupMembershipClaims on the app registration); map by group_id.
    role_mappings: list[RoleMapping] = Field(default_factory=list)
    default_role: str = "viewer"


class OidcSettings(BaseModel):
    enabled: bool = False
    display_name: str = "SSO"
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    email_claim: str = "email"
    username_claim: str = "preferred_username"
    groups_claim: str = "groups"
    role_mappings: list[RoleMapping] = Field(default_factory=list)
    default_role: str = "viewer"


class SamlSettings(BaseModel):
    enabled: bool = False
    display_name: str = "SAML SSO"
    sp_entity_id: str = ""  # blank → derived from public_url
    idp_metadata_url: str = ""  # auto-config; overrides the manual trio below
    idp_entity_id: str = ""
    idp_sso_url: str = ""
    idp_x509_cert: str = ""  # PEM body, verifies the assertion signature
    # Assertion attribute names to read identity + groups from.
    attr_username: str = "username"
    attr_email: str = "email"
    attr_display_name: str = "displayName"
    attr_groups: str = "groups"
    # Matched against the values of the groups attribute (put the value in `group`).
    role_mappings: list[RoleMapping] = Field(default_factory=list)
    default_role: str = "viewer"


class LdapSettings(BaseModel):
    enabled: bool = False
    url: str = ""  # ldap://host:389 or ldaps://host:636
    starttls: bool = False
    bind_dn: str = ""
    bind_password: str = ""
    base_dn: str = ""
    user_filter: str = "(mail={username})"
    email_attr: str = "mail"
    display_name_attr: str = "displayName"
    group_base_dn: str = ""
    group_filter: str = "(member={user_dn})"
    # Matched against the user's group DNs (put the group DN in `group`).
    role_mappings: list[RoleMapping] = Field(default_factory=list)
    default_role: str = "viewer"


# ─── Helpers ──────────────────────────────────────────────────────────────────


class GeneralSettings(BaseModel):
    # Capped so a long brand can't break the sidebar / login layout.
    app_name: str = Field(default="VortexFlow", max_length=40)
    session_timeout: int = 60
    lockout_attempts: int = 5
    lockout_duration: int = 900
    # Fleet-wide desired Vector version. Agents reconcile their host to this
    # (install + restart) before applying config. Empty = don't manage version.
    desired_vector_version: str = ""


class TlsSettings(BaseModel):
    # cert_id: reference a cert from the certificate store (preferred)
    cert_id: Optional[str] = None
    # Applied paths — populated by /settings/tls/apply; read-only for display
    cert_path: str = ""
    key_path: str = ""
    ca_path: str = ""


class NotificationsSettings(BaseModel):
    # How often the background worker reconciles events + drains the outbox.
    tick_interval_secs: int = 30


_VALID_KEYS = {
    "sso_azure",
    "sso_oidc",
    "sso_saml",
    "sso_ldap",
    "general",
    "tls",
    "notifications",
}

_DEFAULTS: dict[str, BaseModel] = {
    "sso_azure": AzureSettings(),
    "sso_oidc": OidcSettings(),
    "sso_saml": SamlSettings(),
    "sso_ldap": LdapSettings(),
    "general": GeneralSettings(),
    "tls": TlsSettings(),
    "notifications": NotificationsSettings(),
}


async def _get_setting(key: str, db: AsyncSession) -> dict:
    row = await db.get(SystemSetting, key)
    if row is None:
        return _DEFAULTS[key].model_dump()
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return _DEFAULTS[key].model_dump()


async def _put_setting(key: str, value: dict, db: AsyncSession) -> None:
    row = await db.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=json.dumps(value))
        db.add(row)
    else:
        row.value = json.dumps(value)
    await db.commit()


# ─── GET all ─────────────────────────────────────────────────────────────────


@router.get("")
async def get_all_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    _secret_fields = {
        "sso_azure": ("client_secret",),
        "sso_oidc": ("client_secret",),
        "sso_ldap": ("bind_password",),
    }
    out: dict[str, dict] = {}
    for key in _VALID_KEYS:
        data = await _get_setting(key, db)
        if key in _secret_fields:
            data = _mask_secrets(data, *_secret_fields[key])
        out[key] = data
    return out


# ─── Azure Entra ID ──────────────────────────────────────────────────────────


def _mask_secrets(data: dict, *fields: str) -> dict:
    """Replace stored secret values with the MASK sentinel so they never reach
    the browser. An empty/absent secret stays empty (nothing to hide)."""
    out = dict(data)
    for f in fields:
        if out.get(f):
            out[f] = MASK
    return out


def _preserve_secrets(new: dict, stored: dict, *fields: str) -> dict:
    """On write, keep the stored secret when the client sends back the MASK
    sentinel (or nothing); only a real, new value replaces it."""
    out = dict(new)
    for f in fields:
        if out.get(f) in (MASK, "", None):
            out[f] = stored.get(f, "")
    return out


@router.get("/sso/azure", response_model=AzureSettings)
async def get_azure(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AzureSettings:
    data = await _get_setting("sso_azure", db)
    return AzureSettings(**_mask_secrets(data, "client_secret"))


@router.put("/sso/azure", response_model=AzureSettings)
async def put_azure(
    body: AzureSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AzureSettings:
    stored = await _get_setting("sso_azure", db)
    payload = _preserve_secrets(body.model_dump(), stored, "client_secret")
    await _put_setting("sso_azure", payload, db)
    logger.info("Azure SSO settings updated")
    return AzureSettings(**_mask_secrets(payload, "client_secret"))


# ─── Generic OIDC ────────────────────────────────────────────────────────────


@router.get("/sso/oidc", response_model=OidcSettings)
async def get_oidc(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> OidcSettings:
    data = await _get_setting("sso_oidc", db)
    return OidcSettings(**_mask_secrets(data, "client_secret"))


@router.put("/sso/oidc", response_model=OidcSettings)
async def put_oidc(
    body: OidcSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> OidcSettings:
    stored = await _get_setting("sso_oidc", db)
    payload = _preserve_secrets(body.model_dump(), stored, "client_secret")
    await _put_setting("sso_oidc", payload, db)
    logger.info("OIDC SSO settings updated")
    return OidcSettings(**_mask_secrets(payload, "client_secret"))


# ─── SAML 2.0 ────────────────────────────────────────────────────────────────


@router.get("/sso/saml", response_model=SamlSettings)
async def get_saml(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> SamlSettings:
    data = await _get_setting("sso_saml", db)
    return SamlSettings(**data)


@router.put("/sso/saml", response_model=SamlSettings)
async def put_saml(
    body: SamlSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> SamlSettings:
    await _put_setting("sso_saml", body.model_dump(), db)
    logger.info("SAML SSO settings updated")
    return body


# ─── General ─────────────────────────────────────────────────────────────────


@router.get("/general", response_model=GeneralSettings)
async def get_general(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> GeneralSettings:
    data = await _get_setting("general", db)
    return GeneralSettings(**data)


@router.put("/general", response_model=GeneralSettings)
async def put_general(
    body: GeneralSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> GeneralSettings:
    await _put_setting("general", body.model_dump(), db)
    logger.info("General settings updated")
    return body


# ─── TLS ─────────────────────────────────────────────────────────────────────


@router.get("/tls", response_model=TlsSettings)
async def get_tls(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> TlsSettings:
    data = await _get_setting("tls", db)
    return TlsSettings(**data)


@router.put("/tls", response_model=TlsSettings)
async def put_tls(
    body: TlsSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> TlsSettings:
    await _put_setting("tls", body.model_dump(), db)
    logger.info("TLS settings updated")
    return body


# ─── Notifications ───────────────────────────────────────────────────────────


@router.get("/notifications", response_model=NotificationsSettings)
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> NotificationsSettings:
    data = await _get_setting("notifications", db)
    return NotificationsSettings(**data)


@router.put("/notifications", response_model=NotificationsSettings)
async def put_notifications(
    body: NotificationsSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> NotificationsSettings:
    if body.tick_interval_secs < 5:
        raise HTTPException(status_code=422, detail="tick_interval_secs must be >= 5")
    await _put_setting("notifications", body.model_dump(), db)
    logger.info("Notification settings updated")
    return body


class TlsApplyResponse(BaseModel):
    cert_path: str
    key_path: str
    ca_path: Optional[str]
    message: str


@router.post("/tls/apply", response_model=TlsApplyResponse)
async def apply_tls(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> TlsApplyResponse:
    """
    Write the selected certificate's PEM files to disk so nginx can load them.
    Reads cert_id from TLS settings, decrypts the key, writes to CERTS_DIR.
    """
    data = await _get_setting("tls", db)
    cert_id: Optional[str] = data.get("cert_id")
    if not cert_id:
        raise HTTPException(
            status_code=400, detail="No certificate selected in TLS settings"
        )

    cert = await db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Selected certificate not found")

    if not cert.key_pem_encrypted:
        raise HTTPException(
            status_code=400,
            detail="Selected certificate has no private key — cannot use for TLS termination",
        )

    key_pem = cert_crypto.decrypt(cert.key_pem_encrypted, app_settings.secret_key)

    try:
        paths = cert_crypto.write_tls_files(
            cert_pem=cert.cert_pem,
            key_pem=key_pem,
            ca_chain_pem=cert.ca_chain_pem,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to write cert files: {exc}"
        )

    # Persist the applied paths back into TLS settings
    data["cert_path"] = paths["cert"]
    data["key_path"] = paths["key"]
    data["ca_path"] = paths.get("ca", "")
    await _put_setting("tls", data, db)

    logger.info("TLS cert applied to disk from store: %s (%s)", cert.label, cert.id)
    return TlsApplyResponse(
        cert_path=paths["cert"],
        key_path=paths["key"],
        ca_path=paths.get("ca"),
        message=f"Certificate '{cert.label}' written to disk. Reload nginx to apply.",
    )


# ─── LDAP / Active Directory ─────────────────────────────────────────────────


@router.get("/sso/ldap", response_model=LdapSettings)
async def get_ldap(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> LdapSettings:
    data = await _get_setting("sso_ldap", db)
    return LdapSettings(**_mask_secrets(data, "bind_password"))


@router.put("/sso/ldap", response_model=LdapSettings)
async def put_ldap(
    body: LdapSettings,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> LdapSettings:
    stored = await _get_setting("sso_ldap", db)
    payload = _preserve_secrets(body.model_dump(), stored, "bind_password")
    await _put_setting("sso_ldap", payload, db)
    logger.info("LDAP settings updated")
    return LdapSettings(**_mask_secrets(payload, "bind_password"))


# ─── AI assistant (BYO-LLM) ──────────────────────────────────────────────────
#
# Stored separately from the generic settings keys above because the API key is
# Fernet-encrypted at rest and masked on read — it must never round-trip through
# the generic get-all blob. See app/services/ai_config.py.


class AiSettingsRead(BaseModel):
    """Config returned to the admin client — never carries the secret."""

    enabled: bool = False
    provider: str = "anthropic"
    base_url: str = ""
    model: str = "claude-opus-4-8"
    redact_fields: list[str] = Field(default_factory=list)
    # True if an API key is stored. The client shows a masked placeholder and
    # only sends a real value when the admin changes it.
    api_key_set: bool = False
    # True if a key is stored but won't decrypt (VORTEXFLOW_SECRET_KEY changed).
    # The UI surfaces this so the admin knows to re-enter or clear the key.
    key_error: bool = False


class AiSettingsWrite(BaseModel):
    # Bounded lengths keep the admin-only config blob (system_settings is TEXT)
    # from growing unboundedly; values themselves are validated in the route.
    enabled: bool = False
    provider: str = Field(default="anthropic", max_length=32)
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="claude-opus-4-8", max_length=120)
    redact_fields: list[str] = Field(default_factory=list, max_length=200)
    # MASK (or empty) ⇒ keep the stored key unchanged; any other value replaces it.
    api_key: str = Field(default=MASK, max_length=500)
    # Explicit removal of the stored key (empty input alone preserves it).
    clear_api_key: bool = False


def _ai_read(raw: dict) -> AiSettingsRead:
    """Build the read model, flagging a stored-but-undecryptable key."""
    pub = ai_config.public_view(raw)
    key_error = pub["api_key_set"] and (
        ai_config.get_api_key(raw, app_settings.secret_key) is None
    )
    return AiSettingsRead(**pub, key_error=key_error)


def _validate_base_url(url: str) -> None:
    """Require a well-formed http(s) URL. Format check only — SSRF egress
    controls on outbound requests are handled in B2 (the LLM client)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=422,
            detail="base_url must be a full http(s) URL, e.g. http://localhost:11434/v1",
        )


@router.get("/ai", response_model=AiSettingsRead)
async def get_ai(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AiSettingsRead:
    raw = await ai_config.load_raw(db)
    return _ai_read(raw)


@router.put("/ai", response_model=AiSettingsRead)
async def put_ai(
    body: AiSettingsWrite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AiSettingsRead:
    if body.provider not in ai_config.PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"provider must be one of {sorted(ai_config.PROVIDERS)}",
        )
    if not body.model.strip():
        raise HTTPException(status_code=422, detail="model is required")

    base_url = body.base_url.strip()
    if body.provider == "self_hosted" and not base_url:
        raise HTTPException(
            status_code=422,
            detail="base_url is required for a self-hosted (OpenAI-compatible) endpoint",
        )
    if base_url:
        _validate_base_url(base_url)

    # Resolve the key: explicit clear wins; else MASK/empty keeps the stored
    # value and a real value replaces it.
    raw = await ai_config.load_raw(db)
    incoming = body.api_key
    if body.clear_api_key:
        raw["api_key_encrypted"] = ""
    elif incoming and incoming != MASK:
        raw["api_key_encrypted"] = ai_config.encrypt_api_key(
            incoming, app_settings.secret_key
        )
    # else: leave raw["api_key_encrypted"] as loaded (unchanged)
    has_key = bool(raw.get("api_key_encrypted"))

    # A keyed provider can't actually run without a key — block enabling blind.
    if body.enabled and body.provider in ai_config.KEYED_PROVIDERS and not has_key:
        raise HTTPException(
            status_code=422,
            detail=f"an API key is required to enable the {body.provider} provider",
        )

    raw["enabled"] = body.enabled
    raw["provider"] = body.provider
    raw["base_url"] = base_url
    raw["model"] = body.model.strip()
    raw["redact_fields"] = [f.strip() for f in body.redact_fields if f.strip()]

    await ai_config.save_raw(db, raw)
    logger.info("AI assistant settings updated (provider=%s)", body.provider)
    await audit.record(
        action="settings.ai_update",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="settings",
        resource_id="ai",
        detail=(
            f"provider={body.provider} model={raw['model']} "
            f"enabled={body.enabled} key_set={has_key}"
        ),
    )
    return _ai_read(raw)


class AiTestResult(BaseModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int | None = None
    sample: str | None = None
    error: str | None = None


@router.post("/ai/test", response_model=AiTestResult)
async def test_ai(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AiTestResult:
    """Probe the **saved** AI config with a tiny prompt (save before testing).

    Uses the stored config so no key round-trips through the request. The error
    string is sanitized by ai_client (no raw upstream body) — see its SSRF note.
    """
    # Bound how fast an admin can probe an arbitrary base_url (timing-oracle SSRF).
    if not await check_rate_limit(f"ai_test_rate:{current_user.id}", 20):
        raise HTTPException(
            status_code=429,
            detail="AI test rate limit exceeded. Maximum 20 requests per minute.",
        )
    raw = await ai_config.load_raw(db)
    result = await ai_client.test_connection(raw, app_settings.secret_key)
    await audit.record(
        action="settings.ai_test",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="settings",
        resource_id="ai",
        detail=f"provider={result.provider} model={result.model} ok={result.ok}",
    )
    return AiTestResult(
        ok=result.ok,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        sample=result.sample,
        error=result.error,
    )
