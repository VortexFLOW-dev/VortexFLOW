# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Personal access tokens (PATs) — programmatic API credentials.

A user manages their OWN tokens. A PAT acts as its owner and inherits that user's
role live, so all existing RBAC applies. Management requires an interactive login
(``get_session_user`` rejects PAT auth) so a leaked token can't mint or revoke
siblings. The secret is shown exactly once, at creation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth import get_session_user
from app.models.api_token import ApiToken
from app.models.user import User
from app.services import api_token, audit

router = APIRouter()

# Cap token lifetime configurability; None = no expiry.
_MAX_EXPIRY_DAYS = 3650


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=_MAX_EXPIRY_DAYS)


class TokenMeta(BaseModel):
    id: str
    token_id: str
    name: str
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenCreated(TokenMeta):
    # The full secret — returned ONCE, never again.
    token: str


@router.get("", response_model=list[TokenMeta])
async def list_tokens(
    user: User = Depends(get_session_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiToken]:
    rows = (
        (
            await db.execute(
                select(ApiToken)
                .where(ApiToken.user_id == user.id)
                .order_by(ApiToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: CreateTokenRequest,
    request: Request,
    user: User = Depends(get_session_user),
    db: AsyncSession = Depends(get_db),
) -> TokenCreated:
    token_id, secret, full = api_token.generate()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days
        else None
    )
    row = ApiToken(
        token_id=token_id,
        token_hash=api_token.hash_secret(secret),
        user_id=user.id,
        name=body.name,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    await audit.record(
        action="token.create",
        user_id=user.id,
        user_email=user.email,
        resource_type="api_token",
        resource_id=row.id,
        ip=_client_ip(request),
        detail=f"name={body.name!r}",
    )
    return TokenCreated(
        id=row.id,
        token_id=row.token_id,
        name=row.name,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        token=full,
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: str,
    request: Request,
    user: User = Depends(get_session_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Scope strictly to the caller's own tokens (by primary key id).
    row = (
        await db.execute(
            select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    await db.execute(delete(ApiToken).where(ApiToken.id == row.id))
    await db.commit()
    await audit.record(
        action="token.revoke",
        user_id=user.id,
        user_email=user.email,
        resource_type="api_token",
        resource_id=row.id,
        ip=_client_ip(request),
        detail=f"name={row.name!r}",
    )
