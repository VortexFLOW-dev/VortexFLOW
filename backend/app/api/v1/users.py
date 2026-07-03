# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_password_hash, validate_password_policy
from app.middleware.rbac import require_admin, require_viewer
from app.models.user import User
from app.services import audit
from app.schemas.user import (
    ResetPasswordRequest,
    ResetPasswordResponse,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)

router = APIRouter()


@router.get("", response_model=UserListResponse)
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserListResponse:
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    total = await db.scalar(select(func.count()).select_from(User)) or 0
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users], total=total
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> UserResponse:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already in use"
        )

    if body.role not in ("admin", "editor", "viewer"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role"
        )

    if body.password:
        try:
            validate_password_policy(body.password)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    user = User(
        email=body.email,
        name=body.name,
        role=body.role,
        auth_method="local",
        hashed_password=get_password_hash(body.password) if body.password else None,
        is_active=True,
        # If the admin set the initial password, force the user to rotate the
        # admin-known value on first login (same intent as reset_password).
        must_change_password=bool(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit.record(
        action="user.create",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="user",
        resource_id=user.id,
        detail=f"created {user.email} as {user.role}",
    )
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_viewer),
) -> UserResponse:
    # Users can fetch themselves; admins can fetch anyone
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_viewer),
) -> UserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Non-admins can only update their own name
    if current_user.role != "admin":
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
            )
        if body.role is not None or body.is_active is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change role or active status",
            )

    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        if body.role not in ("admin", "editor", "viewer"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role"
            )
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ResetPasswordResponse:
    """Admin reset of a LOCAL account's password. If no password is supplied, a
    strong one is generated and returned once. SSO accounts are managed by the
    identity provider and cannot be reset here."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if user.auth_method != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is managed by the SSO provider for this account",
        )

    generated = body.new_password is None
    password = body.new_password or secrets.token_urlsafe(12)
    try:
        validate_password_policy(password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    user.hashed_password = get_password_hash(password)
    user.locked_until = None  # clear any brute-force lockout on reset
    user.must_change_password = True  # force the user to set their own on next login
    db.add(user)
    await db.commit()
    await audit.record(
        action="user.reset_password",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="user",
        resource_id=user.id,
        detail=f"reset password for {user.email}",
    )
    return ResetPasswordResponse(
        generated=generated, password=password if generated else None
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    deleted_email = user.email
    await db.delete(user)
    await db.commit()
    await audit.record(
        action="user.delete",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="user",
        resource_id=user_id,
        detail=f"deleted {deleted_email}",
    )
