# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt hashes only the first 72 bytes of its input and ignores the rest, so
# two different passwords sharing a 72-byte prefix would be equivalent. Reject
# anything longer at policy time rather than silently truncating.
BCRYPT_MAX_BYTES = 72
MIN_PASSWORD_LENGTH = 8


def validate_password_policy(
    password: str, *, min_length: int = MIN_PASSWORD_LENGTH
) -> None:
    """Raise ``ValueError`` if the password violates policy. Enforces a minimum
    length and bcrypt's 72-byte input limit (see ``BCRYPT_MAX_BYTES``)."""
    if len(password) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters")
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes "
            "(a longer password would be silently truncated by bcrypt)"
        )


def get_password_hash(password: str) -> str:
    # Defense in depth: never hash a >72-byte password (silent truncation).
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("Password exceeds the maximum length")
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# A precomputed bcrypt hash to verify against when an auth path has no real hash
# to check (unknown account/instance). Burning one bcrypt cycle either way keeps
# response timing from revealing whether the identifier exists.
_DUMMY_HASH = pwd_context.hash("vortexflow-timing-equalizer")


def dummy_verify() -> None:
    """Burn one bcrypt verify — timing padding for absent-secret auth paths."""
    pwd_context.verify("x", _DUMMY_HASH)


def create_access_token(
    subject: Any,
    sid: Optional[str] = None,
    sst: Optional[int] = None,
    extra: Optional[dict] = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload: dict = {
        "sub": str(subject),
        "exp": expire,
        "type": "access",
        "jti": str(_uuid.uuid4()),
    }
    # sid = session id (Redis-backed idle window); sst = session start epoch
    # (signed, so the absolute cap is tamper-proof without a Redis lookup).
    if sid is not None:
        payload["sid"] = sid
    if sst is not None:
        payload["sst"] = sst
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(
    subject: Any, sid: Optional[str] = None, sst: Optional[int] = None
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
        "jti": str(_uuid.uuid4()),
    }
    if sid is not None:
        payload["sid"] = sid
    if sst is not None:
        payload["sst"] = sst
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except JWTError:
        raise ValueError("Invalid or expired token")
