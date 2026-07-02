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


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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
