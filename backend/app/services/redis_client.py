# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Redis client — async singleton with graceful degradation.

If Redis is unavailable: token revocation is skipped (tokens remain valid
until natural expiry) and the login brute-force counters degrade open (a local
Redis outage should not lock every user out). The generic rate limiter
(``check_rate_limit``) degrades open by default too, but honours
``settings.rate_limit_fail_closed`` to deny instead; either way the degradation
is logged so an outage that drops abuse protection is visible.

Key namespaces:
  revoked:{jti}   → "1"  TTL=remaining token lifetime
  rt:{jti}        → user_id  TTL=refresh token lifetime
  sso:{state}     → "1"  TTL=600s  (SSO CSRF state)
  login_fail:{id} → count  (brute-force per account)
  ip_fail:{ip}    → count  (brute-force per IP)
"""

import logging
from typing import Final, Optional

log = logging.getLogger("vortexflow.redis")

# Sentinel: Redis could not be reached, so a lookup's result is unknown. Callers
# distinguish this from a genuine miss (None) to fail open on outage but closed
# on a real replay/absence.
REDIS_UNAVAILABLE: Final = object()

_client = None  # redis.asyncio.Redis | None


async def _get() -> Optional[object]:
    global _client
    if _client is None:
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            from app.core.config import settings

            _client = aioredis.from_url(
                settings.redis_url, decode_responses=True, socket_connect_timeout=2
            )
            await _client.ping()  # type: ignore[attr-defined]
        except Exception as e:
            log.warning(f"Redis unavailable: {e}")
            _client = None
    return _client


async def revoke_token(jti: str, ttl_seconds: int) -> None:
    r = await _get()
    if r is None:
        return
    try:
        await r.set(f"revoked:{jti}", "1", ex=ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Redis revoke_token failed: {e}")


async def is_token_revoked(jti: str) -> bool:
    r = await _get()
    if r is None:
        return False
    try:
        return bool(await r.exists(f"revoked:{jti}"))  # type: ignore[attr-defined]
    except Exception:
        return False


async def store_refresh_token(jti: str, user_id: str, ttl_seconds: int) -> None:
    r = await _get()
    if r is None:
        return
    try:
        await r.set(f"rt:{jti}", user_id, ex=ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Redis store_refresh_token failed: {e}")


async def consume_refresh_token(jti: str) -> Optional[str] | object:
    """Atomically read+delete a refresh token's replay-guard entry.

    Returns the stored user id (valid single use), ``None`` if the entry is
    absent (already consumed → replay, or never stored), or
    ``REDIS_UNAVAILABLE`` if Redis could not be reached (caller fails open).
    """
    r = await _get()
    if r is None:
        return REDIS_UNAVAILABLE
    try:
        return await r.getdel(f"rt:{jti}")  # type: ignore[attr-defined]
    except Exception:
        return REDIS_UNAVAILABLE


async def start_session(sid: str, user_id: str, ttl_seconds: int) -> None:
    """Create/re-arm a session's idle window."""
    r = await _get()
    if r is None:
        return
    try:
        await r.set(f"session:{sid}", user_id, ex=ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Redis start_session failed: {e}")


async def touch_session(sid: str, ttl_seconds: int) -> bool:
    """Slide the idle window. Returns True if the session is still alive (or if
    Redis is unavailable — fail open), False if it has idle-expired."""
    r = await _get()
    if r is None:
        return True  # degrade open — do not lock users out on a Redis outage
    try:
        return bool(await r.expire(f"session:{sid}", ttl_seconds))  # type: ignore[attr-defined]
    except Exception:
        return True


async def end_session(sid: str) -> None:
    """Terminate a session immediately (logout)."""
    r = await _get()
    if r is None:
        return
    try:
        await r.delete(f"session:{sid}")  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Redis end_session failed: {e}")


async def set_sso_state(state: str, ttl: int = 600) -> None:
    r = await _get()
    if r is None:
        return
    try:
        await r.set(f"sso:{state}", "1", ex=ttl)  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Redis set_sso_state failed: {e}")


async def consume_sso_state(state: str) -> bool:
    r = await _get()
    if r is None:
        return True  # degrade: allow
    try:
        val = await r.getdel(f"sso:{state}")  # type: ignore[attr-defined]
        return val is not None
    except Exception:
        return True


async def record_login_failure(identifier: str, ttl: int = 900) -> int:
    r = await _get()
    if r is None:
        return 0
    try:
        key = f"login_fail:{identifier}"
        count = await r.incr(key)  # type: ignore[attr-defined]
        # Only anchor the TTL on the first failure — subsequent calls must NOT
        # reset it, otherwise a slow-drip attack perpetually resets the window
        # and the counter never accumulates to the lockout threshold.
        if count == 1:
            await r.expire(key, ttl)  # type: ignore[attr-defined]
        return int(count)
    except Exception:
        return 0


async def clear_login_failures(identifier: str) -> None:
    r = await _get()
    if r is None:
        return
    try:
        await r.delete(f"login_fail:{identifier}")  # type: ignore[attr-defined]
    except Exception:
        pass


async def get_login_failures(identifier: str) -> int:
    r = await _get()
    if r is None:
        return 0
    try:
        val = await r.get(f"login_fail:{identifier}")  # type: ignore[attr-defined]
        return int(val) if val else 0
    except Exception:
        return 0


async def set_value(key: str, value: str, ex: int) -> None:
    r = await _get()
    if r is None:
        return
    try:
        await r.set(key, value, ex=ex)  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Redis set_value failed: {e}")


async def exists(key: str) -> bool:
    r = await _get()
    if r is None:
        return False
    try:
        return bool(await r.exists(key))  # type: ignore[attr-defined]
    except Exception:
        return False


async def get_and_delete(key: str) -> Optional[str]:
    r = await _get()
    if r is None:
        return None
    try:
        return await r.getdel(key)  # type: ignore[attr-defined]
    except Exception:
        return None


async def get_ttl(key: str) -> Optional[int]:
    r = await _get()
    if r is None:
        return None
    try:
        val = await r.ttl(key)  # type: ignore[attr-defined]
        return int(val) if val and val > 0 else None
    except Exception:
        return None


def _degrade_allowed() -> bool:
    """What a rate-limit check returns when Redis is unreachable. Fail open by
    default (availability); fail closed when configured. Logged either way so a
    Redis outage that drops abuse protection is visible to operators."""
    from app.core.config import settings

    if settings.rate_limit_fail_closed:
        log.warning("Redis unavailable — rate limit failing CLOSED (denying)")
        return False
    log.warning("Redis unavailable — rate limit failing open (allowing)")
    return True


async def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Increment a sliding counter and return True if the request is allowed."""
    r = await _get()
    if r is None:
        return _degrade_allowed()
    try:
        pipe = r.pipeline()  # type: ignore[attr-defined]
        await pipe.incr(key)
        await pipe.expire(key, window_seconds)
        results = await pipe.execute()
        return int(results[0]) <= limit
    except Exception:
        return _degrade_allowed()
