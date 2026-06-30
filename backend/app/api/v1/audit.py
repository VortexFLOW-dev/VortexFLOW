# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Audit log read API (admin-only).

Lists recorded actions with filtering + pagination, and a CSV export. Writes are
done by ``app.services.audit.record`` from the endpoints being audited.
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import require_admin
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


def _filtered(query, action, resource_type, user_id, q):
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if q:
        like = f"%{q}%"
        query = query.where(
            AuditLog.user_email.ilike(like) | AuditLog.detail.ilike(like)
        )
    return query


@router.get("")
async def list_audit(
    action: str | None = None,
    resource_type: str | None = None,
    user_id: str | None = None,
    q: str | None = Query(default=None, description="search email/detail"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    base = _filtered(select(AuditLog), action, resource_type, user_id, q)
    total = await db.scalar(
        _filtered(
            select(func.count()).select_from(AuditLog),
            action,
            resource_type,
            user_id,
            q,
        )
    )
    rows = (
        (
            await db.execute(
                base.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total or 0,
        "entries": [_entry(r) for r in rows],
    }


@router.get("/export")
async def export_audit(
    action: str | None = None,
    resource_type: str | None = None,
    user_id: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> StreamingResponse:
    """Export the (filtered) audit log as CSV. Capped to the most recent 50k rows."""
    base = _filtered(select(AuditLog), action, resource_type, user_id, q)
    rows = (
        (await db.execute(base.order_by(AuditLog.created_at.desc()).limit(50_000)))
        .scalars()
        .all()
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "timestamp",
            "user_email",
            "action",
            "resource_type",
            "resource_id",
            "ip",
            "detail",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.created_at.isoformat() if r.created_at else "",
                _csv_safe(r.user_email or ""),
                _csv_safe(r.action),
                _csv_safe(r.resource_type or ""),
                _csv_safe(r.resource_id or ""),
                _csv_safe(r.ip_address or ""),
                _csv_safe(r.detail or ""),
            ]
        )
    buf.seek(0)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )


def _csv_safe(v: str) -> str:
    """Neutralize spreadsheet formula injection in CSV cells. A cell beginning
    with one of these characters is executed as a formula by Excel/Sheets; one
    field (a failed-login email) is attacker-influenced. Prefix with a quote."""
    if v and v[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _entry(r: AuditLog) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "user_id": r.user_id,
        "user_email": r.user_email,
        "action": r.action,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "detail": r.detail,
        "ip_address": r.ip_address,
    }
