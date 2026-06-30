# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Shared just-in-time (JIT) user provisioning for all SSO providers.

Every provider (OIDC, Azure, LDAP, …) resolves an external identity to a small
result object, then calls :func:`jit_upsert` to find-or-create the local user.
Centralizing it keeps the identity-matching security rules — stable-subject
match, and refusal to let one auth method claim another's account by email — in
one audited place.
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)

_VALID_ROLES = {"admin", "editor", "viewer"}


class SsoConflict(Exception):
    """An SSO identity collides with an account from a different auth method."""


class SsoResult(Protocol):
    """The shape every provider's auth result must expose for JIT upsert."""

    username: str
    email: str
    display_name: str
    role: str
    external_id: str  # provider's stable subject / DN
    groups: list[str]
    email_verified: bool | None


async def jit_upsert(result: SsoResult, auth_method: str, db: AsyncSession) -> User:
    """Find-or-create the SSO user; the IdP is authoritative for role + groups.

    Match by stable subject within this provider first, then by email. A collision
    with an account from a *different* auth method (local or another SSO provider)
    is refused — we never let one provider claim another's (esp. admin) login by
    asserting a matching email. A same-provider email match bound to a different
    subject is also refused rather than silently rebound.
    """
    role = result.role if result.role in _VALID_ROLES else "viewer"
    groups_str = ",".join(result.groups) if result.groups else None

    # 1) Stable match on subject within this provider (survives email changes).
    user = (
        await db.execute(
            select(User).where(
                User.sso_subject == result.external_id,
                User.auth_method == auth_method,
            )
        )
    ).scalar_one_or_none()

    # 2) Fall back to email.
    if user is None:
        user = (
            await db.execute(select(User).where(User.email == result.email))
        ).scalar_one_or_none()
        # Email belongs to an account from a different auth method: refuse.
        if user is not None and user.auth_method != auth_method:
            raise SsoConflict(
                f"email {result.email} already belongs to a {user.auth_method} account"
            )
        # Same provider, matched by email, but bound to a DIFFERENT stable
        # subject: refuse rather than silently rebind (the subject is the
        # authoritative identity).
        if (
            user is not None
            and user.sso_subject
            and user.sso_subject != result.external_id
        ):
            raise SsoConflict(f"email {result.email} is bound to a different identity")

    if user is None:
        user = User(
            email=result.email,
            name=result.display_name or result.username or result.email,
            hashed_password=None,
            role=role,
            auth_method=auth_method,
            sso_subject=result.external_id,
            sso_groups=groups_str,
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(
            "%s JIT-provisioned user %s (role=%s)", auth_method, user.email, role
        )
        return user

    # Existing SSO user — reconcile mutable fields from the IdP.
    user.name = result.display_name or user.name
    user.role = role
    user.sso_groups = groups_str
    user.sso_subject = result.external_id
    await db.commit()
    await db.refresh(user)
    return user
