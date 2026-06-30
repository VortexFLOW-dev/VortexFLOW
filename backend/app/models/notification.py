# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Notification channel + delivery models — Stage 3 of notifications.

External-channel delivery (webhook / Slack / Teams / email) of the same fleet
events that drive the in-app notification center.

``NotificationChannel`` holds an operator-configured destination; its secret
bits (URL, SMTP password) are Fernet-encrypted at rest via ``cert_crypto``.
``NotificationDelivery`` is a durable outbox row — one per (event, channel,
transition) — drained with retry by the background worker.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # webhook | slack | teams | email
    type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Non-secret config, JSON-encoded (e.g. email host/port/from/to).
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Fernet-encrypted JSON of the secret bits (URL, password). Never returned.
    secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # warning | critical — only events at/above this fire the channel.
    min_severity: Mapped[str] = mapped_column(String, nullable=False, default="warning")
    notify_on_resolve: Mapped[bool] = mapped_column(default=True, nullable=False)

    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NotificationDelivery(Base):
    """Durable outbox row. Unique on (event_id, channel_id, transition) so
    enqueue is idempotent (ON CONFLICT DO NOTHING) under concurrent callers."""

    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    # opened | resolved
    transition: Mapped[str] = mapped_column(String, nullable=False)
    # pending | sent | failed
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
