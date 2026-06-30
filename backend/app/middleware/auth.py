# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.api_token import ApiToken
from app.models.user import User
from app.services import api_token

bearer = HTTPBearer(auto_error=False)

_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _user_from_pat(credential: str, db: AsyncSession) -> User:
    """Resolve a personal access token to its owning user (RBAC inherited live)."""
    parsed = api_token.parse(credential)
    if not parsed:
        raise _INVALID
    token_id, secret = parsed
    row = (
        await db.execute(select(ApiToken).where(ApiToken.token_id == token_id))
    ).scalar_one_or_none()
    # Same error whether the id is unknown or the secret is wrong (no oracle).
    if row is None or not api_token.verify(secret, row.token_hash):
        raise _INVALID

    now = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= now:
        raise _INVALID

    user = (
        await db.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise _INVALID

    # Best-effort, throttled last-used stamp (don't write on every request).
    if row.last_used_at is None or (now - row.last_used_at) > timedelta(minutes=1):
        try:
            row.last_used_at = now
            await db.commit()
        except Exception:
            await db.rollback()

    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Personal access token (programmatic) vs. session JWT (interactive login).
    if api_token.is_pat(credentials.credentials):
        return await _user_from_pat(credentials.credentials, db)

    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def get_session_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Like get_current_user, but rejects PAT auth.

    Used for token management so a leaked PAT can't mint sibling tokens or revoke
    others — those actions require an interactive login.
    """
    if credentials and api_token.is_pat(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an interactive login, not an API token",
        )
    return await get_current_user(credentials, db)
