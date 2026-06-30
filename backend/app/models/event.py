# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Event(Base):
    """A first-class fleet event — the foundation for the in-app notification
    center and outbound notification channels. Events are detected server-side
    from the same signals as the home attention feed (agent failures, instance
    offline, cert expiry, Vector version drift, deploy results).

    Deduplication: `dedup_key` identifies a distinct ongoing condition (e.g.
    ``instance_offline:<id>``). A partial unique index enforces at most one
    *unresolved* event per key, so repeated detection passes don't re-insert.
    When a condition clears, the detector stamps `resolved_at`.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Stable machine kind, e.g. "instance_offline", "agent_validate_failed",
    # "agent_reload_failed", "vector_version_drift", "cert_expiring".
    kind: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="warning")
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Distinguishes an ongoing condition; unique among unresolved events.
    dedup_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
