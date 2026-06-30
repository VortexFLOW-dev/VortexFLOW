# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Data retention — prune unbounded operational tables.

The relational DB holds config + operational data, not time-series (that's
VictoriaMetrics). A few tables grow without bound on a long-running install:
audit_log, events, and the notification outbox. This sweep deletes rows older
than the configured age. Each table is independently opt-in: 0 days = keep
forever (the default, so nothing is deleted unless an operator chooses to).

Audit logs are compliance-sensitive — they default to keep-forever; set
VORTEXFLOW_AUDIT_RETENTION_DAYS only with retention requirements in mind.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.event import Event
from app.models.notification import NotificationDelivery

logger = logging.getLogger(__name__)


async def prune_old_records(db: AsyncSession) -> dict[str, int]:
    """Delete rows older than the configured retention. Returns per-table counts."""
    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    plans = [
        ("audit", AuditLog, AuditLog.created_at, settings.audit_retention_days),
        ("events", Event, Event.created_at, settings.event_retention_days),
        (
            "notifications",
            NotificationDelivery,
            NotificationDelivery.created_at,
            settings.notification_retention_days,
        ),
    ]

    deleted_any = False
    for name, model, column, days in plans:
        if not days or days <= 0:
            continue
        cutoff = now - timedelta(days=days)
        result = cast(
            "CursorResult[None]", await db.execute(delete(model).where(column < cutoff))
        )
        counts[name] = result.rowcount or 0
        deleted_any = True

    if deleted_any:
        await db.commit()
    return counts
