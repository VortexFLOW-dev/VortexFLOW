# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Session-bound token issuance and validation.

A session ties an access+refresh token pair to a Redis-backed idle window plus a
signed absolute-lifetime cap. All interactive login paths (local, SSO, refresh)
mint through :func:`issue` so the safeguards apply uniformly. Enforcement fails
open when Redis is unavailable — tokens still expire on their own TTLs.
"""

import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.services import redis_client


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


async def issue(
    user_id: str,
    role: str,
    *,
    sid: str | None = None,
    sst: int | None = None,
) -> tuple[str, str]:
    """Mint an access+refresh pair bound to a session and register both in Redis.

    Pass ``sid``/``sst`` to continue an existing session (refresh); omit them to
    start a new one (login/SSO).
    """
    if sid is None:
        sid = str(uuid.uuid4())
        sst = _now()
    access = create_access_token(user_id, sid=sid, sst=sst, extra={"role": role})
    refresh = create_refresh_token(user_id, sid=sid, sst=sst)

    idle_ttl = settings.session_idle_timeout_minutes * 60
    refresh_ttl = settings.refresh_token_expire_days * 86400
    await redis_client.start_session(sid, user_id, idle_ttl)
    await redis_client.store_refresh_token(
        decode_token(refresh)["jti"], user_id, refresh_ttl
    )
    return access, refresh


async def validate(sid: str | None, sst: int | None) -> bool:
    """True if the session is within the absolute cap and not idle-expired.

    Slides the idle window as a side effect. Fails open (returns True) when Redis
    is down, and grandfathers legacy tokens minted before sessions existed
    (no ``sid``) until they expire on their own TTL.
    """
    if not sid:
        return True
    # A session token must carry a start time. A present sid with no sst never
    # occurs via issue() (both are set together) — treat it as invalid and fail
    # closed rather than run an uncapped session.
    if sst is None or (_now() - sst) > settings.session_absolute_hours * 3600:
        return False
    return await redis_client.touch_session(
        sid, settings.session_idle_timeout_minutes * 60
    )


async def end(sid: str | None) -> None:
    """Terminate a session immediately (logout)."""
    if sid:
        await redis_client.end_session(sid)
