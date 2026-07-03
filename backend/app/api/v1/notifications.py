# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Notification channels API — Stage 3.

Admin-only CRUD for external delivery channels (webhook / Slack / Teams / email)
plus a "send test" action. Secrets are write-only: the API encrypts them on the
way in (Fernet, via ``cert_crypto``) and never returns them.

Note the inherent SSRF surface — channel
management is admin-gated precisely because operators point webhooks at arbitrary
(often internal) URLs by design.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.rbac import require_admin
from app.models.notification import NotificationChannel
from app.models.user import User
from app.services import cert_crypto, notify

logger = logging.getLogger(__name__)
router = APIRouter()

_TYPES = {"webhook", "slack", "teams", "email"}
_SEVERITIES = {"warning", "critical"}


# ─── Schemas ──────────────────────────────────────────────────────────────────


class ChannelCreate(BaseModel):
    type: str
    name: str = Field(max_length=255)
    enabled: bool = True
    # Non-secret config (email host/port/from/to, webhook content-type, …)
    config: dict = Field(default_factory=dict)
    # Secret bits per type: webhook {url, headers}, slack/teams {url}, email {password}
    secret: dict = Field(default_factory=dict)
    min_severity: str = "warning"
    notify_on_resolve: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    enabled: Optional[bool] = None
    config: Optional[dict] = None
    secret: Optional[dict] = None  # only re-encrypted if provided + non-empty
    min_severity: Optional[str] = None
    notify_on_resolve: Optional[bool] = None


class ChannelResponse(BaseModel):
    id: str
    type: str
    name: str
    enabled: bool
    config: dict
    has_secret: bool
    min_severity: str
    notify_on_resolve: bool
    last_success_at: Optional[datetime]
    last_attempt_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime


def _to_response(c: NotificationChannel) -> ChannelResponse:
    try:
        config = json.loads(c.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    return ChannelResponse(
        id=c.id,
        type=c.type,
        name=c.name,
        enabled=c.enabled,
        config=config,
        has_secret=c.secret_encrypted is not None,
        min_severity=c.min_severity,
        notify_on_resolve=c.notify_on_resolve,
        last_success_at=c.last_success_at,
        last_attempt_at=c.last_attempt_at,
        last_error=c.last_error,
        created_at=c.created_at,
    )


def _encrypt_secret(secret: dict) -> Optional[str]:
    if not secret:
        return None
    return cert_crypto.encrypt(json.dumps(secret), settings.at_rest_key)


def _validate_type_severity(type_: str, min_severity: str) -> None:
    if type_ not in _TYPES:
        raise HTTPException(422, f"type must be one of {sorted(_TYPES)}")
    if min_severity not in _SEVERITIES:
        raise HTTPException(422, f"min_severity must be one of {sorted(_SEVERITIES)}")


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[ChannelResponse]:
    rows = (
        (
            await db.execute(
                select(NotificationChannel).order_by(NotificationChannel.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_to_response(c) for c in rows]


@router.post(
    "/channels", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED
)
async def create_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ChannelResponse:
    _validate_type_severity(body.type, body.min_severity)
    channel = NotificationChannel(
        type=body.type,
        name=body.name,
        enabled=body.enabled,
        config_json=json.dumps(body.config or {}),
        secret_encrypted=_encrypt_secret(body.secret),
        min_severity=body.min_severity,
        notify_on_resolve=body.notify_on_resolve,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    logger.info("Notification channel created: %s (%s)", channel.name, channel.type)
    return _to_response(channel)


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ChannelResponse:
    channel = await _get_or_404(channel_id, db)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        channel.name = data["name"]
    if "enabled" in data:
        channel.enabled = data["enabled"]
    if "config" in data and data["config"] is not None:
        channel.config_json = json.dumps(data["config"])
    if "min_severity" in data and data["min_severity"] is not None:
        if data["min_severity"] not in _SEVERITIES:
            raise HTTPException(422, "invalid min_severity")
        channel.min_severity = data["min_severity"]
    if "notify_on_resolve" in data and data["notify_on_resolve"] is not None:
        channel.notify_on_resolve = data["notify_on_resolve"]
    # Only replace the secret when a non-empty one is supplied — lets the UI save
    # other fields without re-entering credentials.
    if data.get("secret"):
        channel.secret_encrypted = _encrypt_secret(data["secret"])
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return _to_response(channel)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    channel = await _get_or_404(channel_id, db)
    await db.delete(channel)
    await db.commit()
    logger.info("Notification channel deleted: %s", channel_id)


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Send a synthetic notification through the real send path."""
    channel = await _get_or_404(channel_id, db)
    try:
        await notify.send_test(channel)
    except ValueError as e:
        # Our own config-validation messages (e.g. "email channel needs host").
        raise HTTPException(status_code=422, detail=str(e)[:200])
    except RuntimeError as e:
        # The send layer raises only sanitized errors here (URL/host/body-free —
        # "HTTP 404 from endpoint", "SMTP delivery failed: SMTPConnectError").
        raise HTTPException(status_code=502, detail=f"Send failed: {str(e)[:200]}")
    except Exception:  # noqa: BLE001
        # Anything unexpected must NOT echo the raw exception: it can carry the
        # target host and connection-refused/timeout/DNS distinction, turning
        # this admin action into an internal port-scan oracle.
        raise HTTPException(
            status_code=502, detail="Send failed: could not deliver to the endpoint"
        )
    return {"ok": True}


async def _get_or_404(channel_id: str, db: AsyncSession) -> NotificationChannel:
    channel = await db.get(NotificationChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel
