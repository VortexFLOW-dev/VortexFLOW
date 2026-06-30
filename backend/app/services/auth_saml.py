# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
SAML 2.0 authentication service.

Covers: ADFS, Ping Identity, Shibboleth, Okta (SAML mode), OneLogin, Keycloak,
        and any SAML 2.0-compliant IdP. Built on python3-saml (onelogin).

SP-initiated, HTTP-Redirect for the AuthnRequest, HTTP-POST for the response:
  1. ``build_auth_request`` → (IdP redirect URL, AuthnRequest id). The caller
     stores the id (Redis) and redirects the browser.
  2. ``process_response`` → validate the SAMLResponse POSTed to the ACS, then
     require its InResponseTo to equal the stored AuthnRequest id (we enforce
     this explicitly — see process_response — so unsolicited/replayed responses
     are rejected). Returns identity + groups → role.

Security posture (do not weaken):
  - ``strict: True`` — without it python3-saml skips Destination/conditions
    checks. This is the single most important setting.
  - ``wantAssertionsSigned: True`` — the assertion must be signed by the IdP;
    python3-saml verifies the signature covers the assertion (XML-signature-
    wrapping defense).
  - ``rejectDeprecatedAlgorithm: True`` — reject SHA-1 / weak signatures.
  - InResponseTo is validated against the stored request id (anti-replay).
  python3-saml parses XML with external entities disabled (XXE-safe).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.core.config import SAMLConfig


@dataclass
class SAMLAuthResult:
    username: str
    email: str
    display_name: str
    role: str
    external_id: str  # SAML NameID (stable subject)
    groups: list[str]
    email_verified: bool | None = None  # N/A for SAML (IdP is authoritative)


class SAMLAuthError(Exception):
    """Raised when the SAML flow fails for any reason."""


def _resolve_role(groups: list[str], cfg: SAMLConfig) -> str:
    groups_lower = {g.lower() for g in groups}
    for mapping in cfg.role_mappings:
        target = (mapping.group or mapping.group_id or "").lower()
        if target and target in groups_lower:
            return mapping.role
    return cfg.default_role


def _get_attr(attributes: dict, name: str, default: str = "") -> str:
    val = attributes.get(name, [])
    if isinstance(val, list):
        return str(val[0]) if val else default
    return str(val) if val else default


def _get_attr_list(attributes: dict, name: str) -> list[str]:
    val = attributes.get(name, [])
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)] if val else []


async def _fetch_idp_metadata(metadata_url: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(metadata_url, timeout=15)
        r.raise_for_status()
    return r.text


def _make_req(cfg: SAMLConfig, post_data: Optional[dict] = None) -> dict:
    """Build python3-saml's request dict from the ACS URL.

    The ACS URL is authoritative (it's what the IdP was told to POST to), so we
    derive the self-url from it. python3-saml compares the response Destination
    against this self-url under strict mode.
    """
    u = urlparse(cfg.acs_url)
    return {
        "https": "on" if u.scheme == "https" else "off",
        "http_host": u.netloc,
        "script_name": u.path,
        "server_port": str(u.port or (443 if u.scheme == "https" else 80)),
        "get_data": {},
        "post_data": post_data or {},
    }


def _build_settings(cfg: SAMLConfig, idp_metadata_xml: Optional[str]) -> dict:
    sp = {
        "entityId": cfg.sp_entity_id,
        "assertionConsumerService": {
            "url": cfg.acs_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        },
        "NameIDFormat": cfg.name_id_format,
    }
    security = {
        "strict": True,
        "wantAssertionsSigned": True,
        "wantMessagesSigned": False,
        "wantNameId": True,
        "requestedAuthnContext": False,
        "rejectDeprecatedAlgorithm": True,
        "authnRequestsSigned": False,
        "wantAssertionsEncrypted": False,
        "wantNameIdEncrypted": False,
    }
    if idp_metadata_xml:
        return {"strict": True, "sp": sp, "idp": {}, "security": security}
    idp: dict = {
        "entityId": cfg.idp_entity_id,
        "singleSignOnService": {
            "url": cfg.idp_sso_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        },
    }
    if cfg.idp_x509_cert:
        idp["x509cert"] = cfg.idp_x509_cert.strip()
    return {"strict": True, "sp": sp, "idp": idp, "security": security}


def _resolve_settings(cfg: SAMLConfig, idp_metadata_xml: Optional[str]) -> dict:
    settings_data = _build_settings(cfg, idp_metadata_xml)
    if idp_metadata_xml:
        from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser

        idp_data = OneLogin_Saml2_IdPMetadataParser.parse(idp_metadata_xml)
        settings_data = OneLogin_Saml2_IdPMetadataParser.merge_settings(
            settings_data, idp_data
        )
        # IdP metadata can advertise WantAuthnRequestsSigned, which the merge
        # turns into authnRequestsSigned=True → demands an SP signing cert we
        # don't carry in v1. Re-assert OUR security stance: we don't sign the
        # AuthnRequest, but the IdP's assertion MUST be signed.
        sec = settings_data.setdefault("security", {})
        sec["authnRequestsSigned"] = False
        sec["wantAssertionsSigned"] = True
        sec["rejectDeprecatedAlgorithm"] = True
        settings_data["strict"] = True
    return settings_data


async def build_auth_request(cfg: SAMLConfig, relay_state: str) -> tuple[str, str]:
    """Return (IdP redirect URL, AuthnRequest id). Store the id for InResponseTo."""
    if not cfg.enabled:
        raise SAMLAuthError("SAML provider is not enabled")
    if not cfg.acs_url:
        raise SAMLAuthError("SAML ACS URL is not configured (set public_url)")

    idp_metadata_xml: Optional[str] = None
    if cfg.idp_metadata_url:
        idp_metadata_xml = await _fetch_idp_metadata(cfg.idp_metadata_url)
    elif not cfg.idp_sso_url:
        raise SAMLAuthError("SAML: configure either idp_metadata_url or idp_sso_url")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _sync_build_auth_request, cfg, idp_metadata_xml, relay_state
    )


def _sync_build_auth_request(
    cfg: SAMLConfig, idp_metadata_xml: Optional[str], relay_state: str
) -> tuple[str, str]:
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except ImportError:
        raise SAMLAuthError("python3-saml package is not installed")

    settings_data = _resolve_settings(cfg, idp_metadata_xml)
    auth = OneLogin_Saml2_Auth(_make_req(cfg), old_settings=settings_data)
    url = auth.login(return_to=relay_state)
    return url, auth.get_last_request_id()


async def process_response(
    cfg: SAMLConfig, saml_response: str, request_id: Optional[str]
) -> SAMLAuthResult:
    """Validate a SAMLResponse POSTed to the ACS, bound to the stored request id."""
    if not cfg.enabled:
        raise SAMLAuthError("SAML provider is not enabled")

    idp_metadata_xml: Optional[str] = None
    if cfg.idp_metadata_url:
        idp_metadata_xml = await _fetch_idp_metadata(cfg.idp_metadata_url)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _sync_process_response, cfg, saml_response, idp_metadata_xml, request_id
    )


def _sync_process_response(
    cfg: SAMLConfig,
    saml_response: str,
    idp_metadata_xml: Optional[str],
    request_id: Optional[str],
) -> SAMLAuthResult:
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except ImportError:
        raise SAMLAuthError("python3-saml package is not installed")

    settings_data = _resolve_settings(cfg, idp_metadata_xml)
    req = _make_req(cfg, post_data={"SAMLResponse": saml_response})
    auth = OneLogin_Saml2_Auth(req, old_settings=settings_data)

    # python3-saml validates InResponseTo == request_id ONLY when the response
    # carries an InResponseTo; it does not, by itself, reject a response that
    # omits it. Since we are strictly SP-initiated (we always hold a request_id),
    # we additionally require the binding to be present and matching below —
    # closing the unsolicited-response gap.
    auth.process_response(request_id=request_id)
    errors = auth.get_errors()
    if errors:
        raise SAMLAuthError(
            f"SAML validation failed: {errors} ({auth.get_last_error_reason()})"
        )
    if not auth.is_authenticated():
        raise SAMLAuthError("SAML authentication was not successful")

    # Enforce the SP-initiated binding explicitly: the response MUST be in
    # response to our AuthnRequest. Rejects unsolicited (no InResponseTo) and
    # mismatched responses even though the assertion is validly IdP-signed.
    in_response_to = auth.get_last_response_in_response_to()
    if not in_response_to or in_response_to != request_id:
        raise SAMLAuthError("SAML response not bound to our AuthnRequest")

    name_id = auth.get_nameid() or ""
    attributes = auth.get_attributes()

    email = _get_attr(attributes, cfg.attr_email)
    username = _get_attr(attributes, cfg.attr_username) or name_id
    display_name = _get_attr(attributes, cfg.attr_display_name) or username
    groups = _get_attr_list(attributes, cfg.attr_groups)

    return SAMLAuthResult(
        username=username or email or name_id,
        email=email,
        display_name=display_name,
        role=_resolve_role(groups, cfg),
        external_id=name_id,
        groups=groups,
    )


async def get_sp_metadata(cfg: SAMLConfig) -> str:
    """Generate SP metadata XML for admins to register VortexFlow at their IdP."""
    if not cfg.acs_url:
        raise SAMLAuthError("SAML ACS URL is not configured (set public_url)")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_get_sp_metadata, cfg)


def _sync_get_sp_metadata(cfg: SAMLConfig) -> str:
    try:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings
    except ImportError:
        raise SAMLAuthError("python3-saml package is not installed")

    saml_settings = OneLogin_Saml2_Settings(
        settings=_build_settings(cfg, None), sp_validation_only=True
    )
    metadata = saml_settings.get_sp_metadata()
    errors = saml_settings.validate_metadata(metadata)
    if errors:
        raise SAMLAuthError(f"SP metadata invalid: {errors}")
    return metadata.decode("utf-8") if isinstance(metadata, bytes) else str(metadata)
