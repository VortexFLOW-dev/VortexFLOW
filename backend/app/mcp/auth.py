# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""PAT authentication for MCP tools.

MCP over streamable HTTP carries the caller's `Authorization: Bearer vf_pat_...`
header on each request. Tools resolve it to a VortexFlow user via the same
`_user_from_pat` path the REST middleware uses, so a token acts as its owner with
that user's role — RBAC is inherited live, and revoked/expired/inactive tokens
are rejected with no user/id oracle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.middleware.auth import _user_from_pat
from app.middleware.rbac import ROLE_HIERARCHY
from app.models.user import User
from app.services import api_token


class McpAuthError(Exception):
    """The MCP request lacked a usable VortexFlow personal access token."""


def _extract_pat(ctx: Context) -> str:
    request = getattr(ctx.request_context, "request", None)
    if request is None:  # e.g. stdio transport — not supported for auth
        raise McpAuthError("no HTTP request on the MCP context")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise McpAuthError(
            "missing bearer token — authenticate with a VortexFlow "
            "personal access token (Authorization: Bearer vf_pat_...)"
        )
    return token


@asynccontextmanager
async def authed_session(ctx: Context) -> AsyncIterator[tuple[AsyncSession, User]]:
    """Yield a DB session and the authenticated caller. Raises `McpAuthError` on
    any auth failure (uniform message — unknown id and bad secret look alike)."""
    token = _extract_pat(ctx)
    if not api_token.is_pat(token):
        raise McpAuthError("bearer token is not a VortexFlow personal access token")
    async with AsyncSessionLocal() as db:
        try:
            user = await _user_from_pat(token, db)
        except Exception as exc:  # noqa: BLE001 — collapse to one opaque failure
            raise McpAuthError("invalid, expired, or revoked token") from exc
        # Mirror the REST role dependencies so MCP genuinely "inherits the user's
        # role" rather than relying on the coincidence of the current role set:
        # a pending forced password change blocks API use even for a valid PAT,
        # and every tool requires at least viewer.
        if user.must_change_password:
            raise McpAuthError("password change required — rotate it in the UI first")
        if ROLE_HIERARCHY.get(user.role, 0) < ROLE_HIERARCHY["viewer"]:
            raise McpAuthError("insufficient role for read access")
        yield db, user


async def require_user(ctx: Context) -> User:
    """Auth-only variant: resolve the caller and RELEASE the DB session before
    returning. For tools that don't touch the DB after auth (e.g. validate_vrl,
    get_catalog) so a pooled connection isn't held across a subprocess/file read.
    """
    async with authed_session(ctx) as (_db, user):
        return user
