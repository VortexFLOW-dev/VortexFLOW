# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
SSO login + callback routes (authorization-code flow).

One router mounted under ``/auth``. Today: generic OIDC. Azure / SAML / LDAP
reuse the same state/JIT/token-issue plumbing and land here next.

Token delivery to the SPA: the SPA is a bearer-token client (tokens in
localStorage). After a successful callback we 302 to the SPA's ``/auth/callback``
route with the tokens in the URL *fragment* (``#access_token=…&refresh_token=…``).
The fragment is never sent to a server and not written to access logs; the SPA
reads it, stores the tokens, and scrubs the URL.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import _set_refresh_cookie
from app.core.config import OIDCConfig
from app.core.database import get_db
from app.core.netutil import client_ip
from app.models.user import User
from app.services import audit, redis_client, session
from app.services.auth_oidc import (
    OIDCAuthError,
    build_auth_url,
    build_pkce_pair,
    exchange_and_verify,
)
from app.services.auth_saml import SAMLAuthError
from app.services.auth_saml import build_auth_request as build_saml_auth_request
from app.services.auth_saml import get_sp_metadata as get_saml_sp_metadata
from app.services.auth_saml import process_response as process_saml_response
from app.services.sso_config import (
    load_azure_config,
    load_oidc_config,
    load_saml_config,
)
from app.services.sso_jit import SsoConflict, jit_upsert

logger = logging.getLogger(__name__)
router = APIRouter()

_STATE_TTL = 600  # seconds an in-flight login may take


def _client_ip(request: Request) -> str:
    return client_ip(request)


def _login_redirect(error: str) -> RedirectResponse:
    """Bounce back to the login page with a short, non-sensitive error code."""
    return RedirectResponse(url=f"/login?sso_error={error}", status_code=302)


def _success_redirect(access_token: str, refresh_token: str) -> RedirectResponse:
    # Only the short-lived access token rides in the fragment (never JS-persisted);
    # the long-lived refresh token is set as an httpOnly cookie, matching the
    # password-login flow so an XSS can't steal it.
    frag = urlencode({"access_token": access_token})
    resp = RedirectResponse(url=f"/auth/callback#{frag}", status_code=302)
    _set_refresh_cookie(resp, refresh_token)
    return resp


async def _issue_session(user: User, provider: str, ip: str) -> RedirectResponse:
    """Issue a VortexFlow session for an authenticated SSO user and redirect."""
    access_token, refresh_token = await session.issue(user.id, user.role)
    await audit.record(
        action="auth.login",
        user_id=user.id,
        user_email=user.email,
        ip=ip,
        detail=provider,
    )
    return _success_redirect(access_token, refresh_token)


# ─── Provider-generic auth-code flow ─────────────────────────────────────────
#
# Generic OIDC and Azure Entra ID are both OIDC auth-code+PKCE flows over a
# JWKS-verified id_token; they differ only in how the OIDCConfig is built (issuer
# source, group claim). Each provider is `(name, auth_method, config-loader)`.

ConfigLoader = Callable[[AsyncSession], Awaitable[OIDCConfig]]


async def _provider_login(
    provider: str, load_cfg: ConfigLoader, db: AsyncSession
) -> RedirectResponse:
    cfg = await load_cfg(db)
    if not cfg.enabled:
        return _login_redirect(f"{provider}_disabled")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, _ = build_pkce_pair()

    try:
        url = await build_auth_url(cfg, state, verifier, nonce)
    except OIDCAuthError as exc:
        logger.warning("%s login could not build auth URL: %s", provider, exc)
        return _login_redirect(f"{provider}_misconfigured")

    # Bind state → (verifier, nonce) server-side; consumed once at callback.
    await redis_client.set_value(
        f"sso:{provider}:{state}",
        json.dumps({"verifier": verifier, "nonce": nonce}),
        ex=_STATE_TTL,
    )
    return RedirectResponse(url=url, status_code=302)


async def _provider_callback(
    provider: str,
    auth_method: str,
    load_cfg: ConfigLoader,
    request: Request,
    db: AsyncSession,
    state: str | None,
    code: str | None,
    error: str | None,
) -> RedirectResponse:
    ip = _client_ip(request)

    if error:
        logger.info("%s IdP returned error: %s", provider, error)
        return _login_redirect(f"{provider}_idp_error")
    if not state or not code:
        return _login_redirect(f"{provider}_bad_request")

    # Consume state atomically — rejects replay and CSRF (unknown/forged state).
    stored = await redis_client.get_and_delete(f"sso:{provider}:{state}")
    if not stored:
        return _login_redirect(f"{provider}_state_expired")
    try:
        bound = json.loads(stored)
        verifier = bound["verifier"]
        nonce = bound["nonce"]
    except (json.JSONDecodeError, KeyError):
        return _login_redirect(f"{provider}_state_invalid")

    cfg = await load_cfg(db)
    try:
        result = await exchange_and_verify(cfg, code, verifier, nonce)
    except OIDCAuthError as exc:
        logger.warning("%s callback verification failed: %s", provider, exc)
        await audit.record(
            action="auth.login_failed", ip=ip, detail=f"{provider}: {exc}"
        )
        return _login_redirect(f"{provider}_verify_failed")

    if not result.email:
        await audit.record(
            action="auth.login_failed", ip=ip, detail=f"{provider}: token has no email"
        )
        return _login_redirect(f"{provider}_no_email")

    # Email is used as a JIT identity key (find-or-create, role assignment). An
    # IdP that explicitly marks the address unverified must not be trusted to
    # bind it — refuse. (Absent claim is allowed: not every IdP emits it.)
    if result.email_verified is False:
        await audit.record(
            action="auth.login_failed",
            user_email=result.email,
            ip=ip,
            detail=f"{provider}: email not verified by IdP",
        )
        return _login_redirect(f"{provider}_email_unverified")

    try:
        user = await jit_upsert(result, auth_method, db)
    except SsoConflict as exc:
        await audit.record(
            action="auth.login_failed",
            user_email=result.email,
            ip=ip,
            detail=f"{provider}: {exc}",
        )
        return _login_redirect(f"{provider}_account_conflict")

    if not user.is_active:
        await audit.record(
            action="auth.login_failed",
            user_id=user.id,
            user_email=user.email,
            ip=ip,
            detail=f"{provider}: account disabled",
        )
        return _login_redirect(f"{provider}_account_disabled")

    return await _issue_session(user, provider, ip)


# ─── Generic OIDC ────────────────────────────────────────────────────────────


@router.get("/oidc/login")
async def oidc_login(db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    return await _provider_login("oidc", load_oidc_config, db)


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    return await _provider_callback(
        "oidc", "oidc", load_oidc_config, request, db, state, code, error
    )


# ─── Azure Entra ID (OIDC) ───────────────────────────────────────────────────


@router.get("/azure/login")
async def azure_login(db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    return await _provider_login("azure", load_azure_config, db)


@router.get("/azure/callback")
async def azure_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    return await _provider_callback(
        "azure", "azure", load_azure_config, request, db, state, code, error
    )


# ─── SAML 2.0 ────────────────────────────────────────────────────────────────
#
# SAML is POST-binding, not a code callback: the IdP POSTs a signed SAMLResponse
# to the ACS. We bind it to the AuthnRequest id (stored in Redis under the
# RelayState token) so unsolicited/replayed responses are rejected.


@router.get("/saml/login")
async def saml_login(db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    cfg = await load_saml_config(db)
    if not cfg.enabled:
        return _login_redirect("saml_disabled")

    state = secrets.token_urlsafe(32)
    try:
        url, request_id = await build_saml_auth_request(cfg, state)
    except SAMLAuthError as exc:
        logger.warning("SAML login could not build AuthnRequest: %s", exc)
        return _login_redirect("saml_misconfigured")

    # Bind RelayState → AuthnRequest id; consumed once at the ACS.
    await redis_client.set_value(
        f"sso:saml:{state}", json.dumps({"request_id": request_id}), ex=_STATE_TTL
    )
    return RedirectResponse(url=url, status_code=302)


@router.post("/saml/acs")
async def saml_acs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    SAMLResponse: str = Form(default=""),
    RelayState: str = Form(default=""),
) -> RedirectResponse:
    ip = _client_ip(request)
    if not SAMLResponse:
        return _login_redirect("saml_bad_request")

    # Consume the RelayState → AuthnRequest id (single-use). A missing/unknown
    # RelayState means no in-flight SP-initiated login: reject (anti-replay/CSRF).
    stored = (
        await redis_client.get_and_delete(f"sso:saml:{RelayState}")
        if RelayState
        else None
    )
    if not stored:
        return _login_redirect("saml_state_expired")
    try:
        request_id = json.loads(stored)["request_id"]
    except (json.JSONDecodeError, KeyError):
        return _login_redirect("saml_state_invalid")

    cfg = await load_saml_config(db)
    try:
        result = await process_saml_response(cfg, SAMLResponse, request_id)
    except SAMLAuthError as exc:
        logger.warning("SAML ACS validation failed: %s", exc)
        await audit.record(action="auth.login_failed", ip=ip, detail=f"saml: {exc}")
        return _login_redirect("saml_verify_failed")

    if not result.email:
        await audit.record(
            action="auth.login_failed", ip=ip, detail="saml: assertion has no email"
        )
        return _login_redirect("saml_no_email")

    try:
        user = await jit_upsert(result, "saml", db)
    except SsoConflict as exc:
        await audit.record(
            action="auth.login_failed",
            user_email=result.email,
            ip=ip,
            detail=f"saml: {exc}",
        )
        return _login_redirect("saml_account_conflict")

    if not user.is_active:
        await audit.record(
            action="auth.login_failed",
            user_id=user.id,
            user_email=user.email,
            ip=ip,
            detail="saml: account disabled",
        )
        return _login_redirect("saml_account_disabled")

    return await _issue_session(user, "saml", ip)


@router.get("/saml/metadata")
async def saml_metadata(db: AsyncSession = Depends(get_db)) -> Response:
    """SP metadata XML — admins upload this to their IdP to register VortexFlow."""
    cfg = await load_saml_config(db)
    try:
        xml = await get_saml_sp_metadata(cfg)
    except SAMLAuthError as exc:
        return Response(content=str(exc), status_code=400)
    return Response(content=xml, media_type="application/xml")
