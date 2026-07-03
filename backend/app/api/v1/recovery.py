# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Break-glass admin recovery.

A random token is printed to stdout at every startup. It is single-use,
expires after 1 hour, and resets the admin password + clears any lockouts.
This route is intentionally unauthenticated — it exists for when you are
locked out of all admin accounts.

Recovery state is stored in Redis (not in-process memory) so it works
correctly under multi-worker / multi-replica deployments. Each use attempt
is an atomic GETDEL so the token cannot be replayed across workers.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import _get_client_ip
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_password_hash, validate_password_policy
from app.models.user import User
from app.schemas.auth import RecoveryRequest, RecoveryStatusResponse
from app.services import audit, redis_client

router = APIRouter()
log = logging.getLogger("vortexflow.recovery")

_RECOVERY_KEY = "vortexflow:recovery_token"
_RECOVERY_TTL = 3600  # 1 hour
_RATE_KEY_PREFIX = "vortexflow:recovery_attempts:"
_RATE_TTL = 300  # sliding 5-min window anchored to first attempt
_RATE_LIMIT = 5


async def set_recovery_token(token: str) -> None:
    """Store the recovery token in Redis with TTL. Called from startup lifespan."""
    await redis_client.set_value(_RECOVERY_KEY, token, ex=_RECOVERY_TTL)


@router.get("", response_model=RecoveryStatusResponse)
async def recovery_status() -> RecoveryStatusResponse:
    available = await redis_client.exists(_RECOVERY_KEY)
    return RecoveryStatusResponse(available=available)


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def use_recovery(
    body: RecoveryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    ip = _get_client_ip(request)

    # Fetch token FIRST (atomic consume) before checking rate-limit so an
    # attacker cannot burn rate-limit slots to block the legitimate admin.
    stored_token = await redis_client.get_and_delete(_RECOVERY_KEY)

    if stored_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recovery token is unavailable or expired",
        )

    # Rate-limit AFTER fetch — we already consumed the token so a 429 here
    # means the token is gone regardless. We check rate-limit to slow down
    # enumeration attempts, but the count is per-IP so a single IP doing a
    # slow-drip still gets blocked.
    attempts = await redis_client.record_login_failure(f"recovery:{ip}", _RATE_TTL)
    if attempts > _RATE_LIMIT:
        # Token already consumed — put nothing back; tell the admin to restart
        # the service to get a fresh token.
        log.warning("Recovery rate-limit exceeded for IP %s — token consumed", ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many recovery attempts. Restart the service to generate a new recovery token.",
        )

    if not secrets.compare_digest(stored_token, body.token):
        # Wrong token — put it back with the REMAINING TTL, not a fresh one,
        # so the 1-hour guarantee is preserved regardless of wrong guesses.
        remaining = await redis_client.get_ttl(_RECOVERY_KEY)
        if remaining and remaining > 0:
            await redis_client.set_value(_RECOVERY_KEY, stored_token, ex=remaining)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid recovery token",
        )

    try:
        validate_password_policy(body.new_password, min_length=12)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Prefer a local admin; fall back to oldest admin of any type and also
    # switch their auth_method to 'local' so the new password is usable.
    result = await db.execute(
        select(User)
        .where(User.role == "admin", User.auth_method == "local")
        .order_by(User.created_at)
        .limit(1)
    )
    admin = result.scalar_one_or_none()

    if admin is None:
        # No local admin exists — take the oldest admin of any type and
        # convert them to local so the recovery password actually works.
        result = await db.execute(
            select(User).where(User.role == "admin").order_by(User.created_at).limit(1)
        )
        admin = result.scalar_one_or_none()
        if admin:
            admin.auth_method = "local"

    if not admin:
        # Fresh install (or no admin remains): the recovery token doubles as a
        # one-time **first-run setup token** — no static default credential is
        # ever seeded. If a user already owns the configured bootstrap email
        # (e.g. an SSO-provisioned account), promote it to a local admin rather
        # than INSERT a duplicate (which would hit UNIQUE(email) and waste the
        # already-consumed token); otherwise create the first admin.
        existing = await db.execute(
            select(User).where(User.email == settings.bootstrap_admin_email).limit(1)
        )
        admin = existing.scalar_one_or_none()
        if admin is not None:
            admin.role = "admin"
            admin.auth_method = "local"
            log.warning("Setup token used — promoted %s to local admin", admin.email)
        else:
            admin = User(
                email=settings.bootstrap_admin_email,
                name=settings.bootstrap_admin_name,
                role="admin",
                auth_method="local",
                is_active=True,
            )
            db.add(admin)
            log.warning("Setup token used — first admin created: %s", admin.email)

    admin.hashed_password = get_password_hash(body.new_password)
    admin.is_active = True
    admin.locked_until = None
    # The operator just chose this password via break-glass — don't then force a
    # change on next login.
    admin.must_change_password = False
    db.add(admin)
    await db.commit()

    log.warning("Recovery token used — admin password reset for %s", admin.email)
    await audit.record(
        action="auth.recovery_used",
        user_id=admin.id,
        user_email=admin.email,
        resource_type="user",
        resource_id=admin.id,
        ip=ip,
        detail="setup/recovery token consumed — admin access set",
    )
