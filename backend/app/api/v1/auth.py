# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    AuthMethodsResponse,
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.services import audit, redis_client
from app.services.auth_ldap import LDAPAuthError
from app.services.auth_ldap import authenticate as ldap_authenticate
from app.services.sso_config import load_ldap_config
from app.services.sso_jit import SsoConflict, jit_upsert

router = APIRouter()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/methods", response_model=AuthMethodsResponse)
async def auth_methods(db: AsyncSession = Depends(get_db)) -> AuthMethodsResponse:
    """
    Return which auth providers are configured — used to render login page.

    DB settings (system_settings table) take precedence over env vars so that
    SSO configured via the Settings UI is reflected immediately on next request.
    Env vars serve as fallback for deployments that predate the Settings UI.
    """
    import json
    from app.models.system_setting import SystemSetting

    async def _db_sso(key: str) -> dict:
        row = await db.get(SystemSetting, key)
        if row:
            try:
                return json.loads(row.value)
            except Exception:
                pass
        return {}

    azure_db = await _db_sso("sso_azure")
    oidc_db = await _db_sso("sso_oidc")
    saml_db = await _db_sso("sso_saml")
    ldap_db = await _db_sso("sso_ldap")

    # DB enabled flag wins; fall back to env var presence
    azure_on = azure_db.get("enabled", False) or bool(
        settings.azure_tenant_id and settings.azure_client_id
    )
    oidc_on = oidc_db.get("enabled", False) or bool(
        settings.oidc_issuer and settings.oidc_client_id
    )
    saml_on = saml_db.get("enabled", False) or bool(
        settings.saml_idp_metadata_url or settings.saml_idp_sso_url
    )
    ldap_on = ldap_db.get("enabled", False) or bool(settings.ldap_url)

    general = await _db_sso("general")
    app_name = str(general.get("app_name") or settings.app_name)

    return AuthMethodsResponse(
        local=True,
        azure=azure_on,
        oidc=oidc_on,
        oidc_display_name=oidc_db.get("display_name") or settings.oidc_display_name,
        saml=saml_on,
        saml_display_name=saml_db.get("display_name") or settings.saml_display_name,
        ldap=ldap_on,
        app_name=app_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    ip = _get_client_ip(request)

    ip_failures = await redis_client.get_login_failures(f"ip:{ip}")
    if ip_failures >= settings.ip_block_threshold:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts from this IP",
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    async def _fail(acct_key: str) -> None:
        await redis_client.record_login_failure(
            acct_key, settings.lockout_duration_seconds
        )
        await redis_client.record_login_failure(
            f"ip:{ip}", settings.ip_block_duration_seconds
        )

    async def _issue(u: User) -> TokenResponse:
        await redis_client.clear_login_failures(f"acct:{u.id}")
        # Note: intentionally NOT clearing ip:{ip} — IP counter is a
        # network-level signal independent of per-user success; clearing it lets
        # a shared-NAT attacker reset their record by sharing an IP with a
        # legitimate user.
        jti = str(uuid.uuid4())
        access = create_access_token(u.id, extra={"role": u.role, "jti": jti})
        refresh = create_refresh_token(u.id)
        refresh_ttl = settings.refresh_token_expire_days * 86400
        rt = decode_token(refresh)
        await redis_client.store_refresh_token(rt["jti"], u.id, refresh_ttl)
        await audit.record(action="auth.login", user_id=u.id, user_email=u.email, ip=ip)
        return TokenResponse(access_token=access, refresh_token=refresh)

    # A disabled account never authenticates, by any method.
    if user is not None and not user.is_active:
        await _fail(f"acct:{user.id}")
        await audit.record(
            action="auth.login_failed",
            user_id=user.id,
            user_email=user.email,
            ip=ip,
            detail="inactive account",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    # ── Local password auth ──────────────────────────────────────────────────
    if user is not None and user.auth_method == "local" and user.hashed_password:
        if await redis_client.get_login_failures(f"acct:{user.id}") >= (
            settings.max_login_attempts
        ):
            await audit.record(
                action="auth.login_locked",
                user_id=user.id,
                user_email=user.email,
                ip=ip,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account locked due to too many failed attempts",
            )
        if not verify_password(body.password, user.hashed_password):
            await _fail(f"acct:{user.id}")
            await audit.record(
                action="auth.login_failed",
                user_id=user.id,
                user_email=user.email,
                ip=ip,
                detail="wrong password",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )
        return await _issue(user)

    # ── LDAP bind auth (transparent on the local form) ───────────────────────
    # Only for unknown emails (first login → JIT) or existing ldap-method users;
    # a local- or other-SSO-bound email never falls through to LDAP.
    if user is None or user.auth_method == "ldap":
        ldap_cfg = await load_ldap_config(db)
        if ldap_cfg.enabled:
            acct_key = f"acct:{user.id}" if user else f"email:{body.email}"
            if await redis_client.get_login_failures(acct_key) >= (
                settings.max_login_attempts
            ):
                if user is not None:
                    await audit.record(
                        action="auth.login_locked",
                        user_id=user.id,
                        user_email=user.email,
                        ip=ip,
                    )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Account locked due to too many failed attempts",
                )
            try:
                ldap_result = await ldap_authenticate(
                    body.email, body.password, ldap_cfg
                )
            except LDAPAuthError:
                await _fail(acct_key)
                await audit.record(
                    action="auth.login_failed",
                    user_email=body.email,
                    ip=ip,
                    detail="ldap: invalid credentials",
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )
            if not ldap_result.email:
                await audit.record(
                    action="auth.login_failed",
                    user_email=body.email,
                    ip=ip,
                    detail="ldap: directory entry has no email",
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )
            try:
                user = await jit_upsert(ldap_result, "ldap", db)
            except SsoConflict:
                await audit.record(
                    action="auth.login_failed",
                    user_email=ldap_result.email,
                    ip=ip,
                    detail="ldap: email belongs to another account",
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )
            if not user.is_active:
                await audit.record(
                    action="auth.login_failed",
                    user_id=user.id,
                    user_email=user.email,
                    ip=ip,
                    detail="ldap: account disabled",
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )
            return await _issue(user)

    # ── Nothing matched: unknown email, SSO-only account, or LDAP disabled ────
    # Stable non-enumerable key when there's no local account, so we don't leak
    # whether the email exists.
    await _fail(f"acct:{user.id}" if user is not None else f"email:{body.email}")
    await audit.record(
        action="auth.login_failed",
        user_id=user.id if user is not None else None,
        user_email=body.email,
        ip=ip,
        detail="no matching auth method",
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token"
        )

    old_jti = payload.get("jti")
    if not old_jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    # Atomic consume — if already used this returns None (replay rejected)
    stored_uid = await redis_client.consume_refresh_token(old_jti)
    user_id = payload.get("sub")
    if stored_uid is not None and stored_uid != user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    jti = str(uuid.uuid4())
    access_token = create_access_token(user.id, extra={"role": user.role, "jti": jti})
    new_refresh = create_refresh_token(user.id)

    # Register new refresh token JTI so it can be consumed exactly once
    refresh_ttl = settings.refresh_token_expire_days * 86400
    new_payload = decode_token(new_refresh)
    await redis_client.store_refresh_token(new_payload["jti"], user.id, refresh_ttl)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: User = Depends(get_current_user)) -> None:
    pass  # Stateless — client discards tokens. JTI revocation added in Phase 5.


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if current_user.auth_method != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password change not available for SSO accounts",
        )
    if not current_user.hashed_password or not verify_password(
        body.current_password, current_user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )
    current_user.hashed_password = get_password_hash(body.new_password)
    current_user.must_change_password = False  # requirement satisfied
    db.add(current_user)
    await db.commit()
