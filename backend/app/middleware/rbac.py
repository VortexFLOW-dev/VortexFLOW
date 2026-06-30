# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from fastapi import Depends, HTTPException, status
from app.middleware.auth import get_current_user
from app.models.user import User

ROLE_HIERARCHY = {"admin": 3, "editor": 2, "viewer": 1}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "users:read",
        "users:write",
        "instances:read",
        "instances:write",
        "pipelines:read",
        "pipelines:write",
        "transforms:read",
        "transforms:write",
        "audit:read",
        "settings:read",
        "settings:write",
    },
    "editor": {
        "instances:read",
        "pipelines:read",
        "pipelines:write",
        "transforms:read",
        "transforms:write",
    },
    "viewer": {
        "instances:read",
        "pipelines:read",
        "transforms:read",
    },
}


def _block_if_password_change_required(user: User) -> None:
    """Enforce the forced-password-change gate server-side, not just in the UI.
    The password-change/me/logout endpoints depend on get_current_user directly
    (not these role checks), so they stay reachable while the rest of the app is
    blocked until the user rotates their password."""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password_change_required",
        )


def require_role(minimum_role: str):
    """Dependency: user must have at least the given role."""

    def _check(current_user: User = Depends(get_current_user)) -> User:
        _block_if_password_change_required(current_user)
        user_level = ROLE_HIERARCHY.get(current_user.role, 0)
        required_level = ROLE_HIERARCHY.get(minimum_role, 999)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _check


def require_permission(permission: str):
    """Dependency: user must have the given permission."""

    def _check(current_user: User = Depends(get_current_user)) -> User:
        _block_if_password_change_required(current_user)
        allowed = ROLE_PERMISSIONS.get(current_user.role, set())
        if permission not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _check


require_admin = require_role("admin")
require_editor = require_role("editor")
require_viewer = require_role("viewer")
