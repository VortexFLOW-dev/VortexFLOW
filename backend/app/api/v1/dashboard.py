# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.rbac import require_viewer
from app.models.instance import Instance
from app.models.fleet import Fleet
from app.models.user import User
from app.services.fleet_view import derive_status, effective_vector_version
from app.services.redis_client import _get as get_redis
from app.services.vm_metrics import (
    fetch_leader_metrics,
    fetch_fleet_metrics,
    fetch_fleet_throughput_series,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _step_for(minutes: int) -> str:
    """Pick a query step that keeps the throughput series ~12-30 points."""
    if minutes <= 30:
        return "1m"
    if minutes <= 180:
        return "5m"
    if minutes <= 720:
        return "30m"
    return "1h"


@router.get("/summary")
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
    minutes: int = Query(default=60, ge=5, le=10080),
    metric: str = Query(default="events", pattern="^(events|bytes)$"),
) -> dict:
    from app.api.v1.settings import _get_setting

    general = await _get_setting("general", db)
    desired_vector_version = str(general.get("desired_vector_version", "") or "")

    fleets_result = await db.execute(select(Fleet).order_by(Fleet.created_at))
    fleets = fleets_result.scalars().all()

    instances_result = await db.execute(
        select(Instance).where(Instance.is_active == True)  # noqa: E712
    )
    all_instances = instances_result.scalars().all()
    instances_by_fleet: dict[str, list[Instance]] = {}
    unassigned: list[Instance] = []
    for inst in all_instances:
        if inst.fleet_id:
            instances_by_fleet.setdefault(inst.fleet_id, []).append(inst)
        else:
            unassigned.append(inst)

    # Derive hostnames from api_url for VM metrics lookup
    all_member_instances = [
        i for members in instances_by_fleet.values() for i in members
    ]
    hostnames = list({_hostname(i.api_url) for i in all_member_instances if i.api_url})

    # host (VM `host` label) → fleet id, for folding per-host series into fleets.
    # Keyed by hostname-without-port, so two instances that share a hostname but
    # live in different fleets (e.g. distinct ports on one box) collapse to one
    # key (last wins) — an edge case the per-host VM series can't disambiguate.
    host_to_fleet = {
        _hostname(i.api_url): i.fleet_id
        for i in all_member_instances
        if i.api_url and i.fleet_id
    }

    # Fetch system health and VM metrics concurrently. Per-fleet throughput
    # series feed the stacked hero; the overall trend is the skyline's height,
    # so no separate total query is needed.
    system, vm_data, leader, fleet_series = await asyncio.gather(
        _check_system_health(),
        fetch_fleet_metrics(hostnames),
        fetch_leader_metrics(),
        fetch_fleet_throughput_series(
            host_to_fleet, minutes=minutes, step=_step_for(minutes), metric=metric
        ),
    )

    now = datetime.now(timezone.utc)
    fleet_summaries = []
    for s in fleets:
        members = instances_by_fleet.get(s.id, [])
        eff_desired = effective_vector_version(s, desired_vector_version)
        fleet_summaries.append(
            {
                "id": s.id,
                "name": s.name,
                "is_default": s.is_default,
                "generation": s.generation,
                "instance_count": len(members),
                "throughput_series": fleet_series.get(s.id, []),
                "desired_vector_version": s.desired_vector_version or "",
                "effective_vector_version": eff_desired,
                "instances": [
                    _member_dict(i, s.generation, eff_desired, now, vm_data)
                    for i in members
                ],
            }
        )

    # Reconcile fleet events for instant in-app bell freshness when a tab is open
    # (idempotent, best-effort). Outbound notification enqueue + dispatch is owned
    # solely by the background worker, so it stays the single delivery driver and
    # this read path never blocks on (or duplicates) notification work.
    from app.services.event_detector import detect_and_record

    await detect_and_record(db)

    return {
        "system": system,
        "leader": leader,
        "desired_vector_version": desired_vector_version,
        "fleets": fleet_summaries,
        "unassigned_instances": len(unassigned),
        "total_instances": len(all_instances),
    }


def _hostname(api_url: str) -> str:
    """Extract hostname from a URL, fallback to the raw string."""
    try:
        return urlparse(api_url).hostname or api_url
    except Exception:
        return api_url


def _member_dict(instance, fleet_generation, desired, now, vm_data) -> dict:
    """One fleet-member instance for the dashboard payload — metrics + status
    via the shared fleet_view logic, so the dot here matches the Instances
    console and the alerts."""
    metrics = vm_data.get(
        _hostname(instance.api_url),
        {
            "events_in_per_sec": 0.0,
            "events_out_per_sec": 0.0,
            "errors_per_sec": 0.0,
            "bytes_in_per_sec": 0.0,
            "bytes_out_per_sec": 0.0,
            "discarded_per_sec": 0.0,
            "buffer_events": 0.0,
            "sink_failed_per_sec": 0.0,
        },
    )
    has_metrics = (
        metrics["events_in_per_sec"] > 0
        or metrics["events_out_per_sec"] > 0
        or metrics["errors_per_sec"] > 0
    )
    s = derive_status(instance, fleet_generation, desired, now, has_metrics)
    return {
        "id": instance.id,
        "label": instance.label,
        "api_url": instance.api_url,
        "role": instance.role,
        "fleet_id": instance.fleet_id,
        "config_push_mode": instance.config_push_mode,
        "applied_generation": instance.applied_generation,
        "agent_status": instance.agent_status,
        "vector_version": instance.vector_version,
        "metrics": metrics,
        "status": {"state": s.state, "reason": s.reason},
    }


async def _check_system_health() -> dict:
    db_ok = True
    redis_ok = True
    vm_ok = True

    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    try:
        r = await get_redis()
        if r:
            await r.ping()  # type: ignore[attr-defined]
        else:
            redis_ok = False
    except Exception:
        redis_ok = False

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.vm_url}/health")
            vm_ok = resp.status_code == 200
    except Exception:
        vm_ok = False

    return {"api": True, "db": db_ok, "redis": redis_ok, "vm": vm_ok}
