# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fleet events API — backs the in-app notification center.

Events are detected server-side (see ``services/event_detector.py``). This
router exposes them read-only plus an acknowledge action. Any authenticated
user (viewer+) may list and acknowledge.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import require_viewer
from app.models.event import Event
from app.models.user import User

router = APIRouter()


class EventOut(BaseModel):
    id: str
    kind: str
    severity: str
    title: str
    body: Optional[str]
    resource_type: Optional[str]
    resource_id: Optional[str]
    created_at: datetime
    acknowledged_at: Optional[datetime]
    resolved_at: Optional[datetime]


class EventListResponse(BaseModel):
    events: list[EventOut]
    unacknowledged: int


def _to_out(e: Event) -> EventOut:
    return EventOut(
        id=e.id,
        kind=e.kind,
        severity=e.severity,
        title=e.title,
        body=e.body,
        resource_type=e.resource_type,
        resource_id=e.resource_id,
        created_at=e.created_at,
        acknowledged_at=e.acknowledged_at,
        resolved_at=e.resolved_at,
    )


@router.get("", response_model=EventListResponse)
async def list_events(
    include_resolved: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> EventListResponse:
    stmt = select(Event)
    if not include_resolved:
        stmt = stmt.where(Event.resolved_at.is_(None))
    stmt = stmt.order_by(Event.created_at.desc()).limit(limit)
    events = (await db.execute(stmt)).scalars().all()

    unack = await db.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.acknowledged_at.is_(None), Event.resolved_at.is_(None))
    )

    return EventListResponse(
        events=[_to_out(e) for e in events],
        unacknowledged=int(unack or 0),
    )


@router.post("/{event_id}/ack", response_model=EventOut)
async def acknowledge_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
) -> EventOut:
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    if event.acknowledged_at is None:
        event.acknowledged_at = datetime.now(timezone.utc)
        event.acknowledged_by = user.id
        await db.commit()
        await db.refresh(event)
    return _to_out(event)


@router.post("/ack-all")
async def acknowledge_all(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
) -> dict:
    now = datetime.now(timezone.utc)
    events = (
        (
            await db.execute(
                select(Event).where(
                    Event.acknowledged_at.is_(None), Event.resolved_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for e in events:
        e.acknowledged_at = now
        e.acknowledged_by = user.id
    await db.commit()
    return {"acknowledged": len(events)}
