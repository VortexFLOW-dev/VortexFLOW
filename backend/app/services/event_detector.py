# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Server-side fleet-event detection.

Mirrors the signals the home attention feed derives client-side, but persists
them as first-class :class:`Event` rows so they can drive the in-app
notification center and (later) outbound notification channels.

Each detected condition has a stable ``dedup_key``. A partial unique index
(``resolved_at IS NULL``) guarantees at most one open event per key, so calling
:func:`detect_and_record` on every dashboard poll is idempotent — it inserts a
row the first time a condition appears and stamps ``resolved_at`` once it clears.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certificate import Certificate
from app.models.event import Event
from app.models.instance import Instance
from app.services.fleet_view import (
    effective_vector_version,
    has_version_drift,
    hostname,
    is_agent_offline,
)
from app.services.vm_metrics import fetch_fleet_metrics

logger = logging.getLogger(__name__)

# Certificates within this many days of expiry raise an event.
CERT_EXPIRY_DAYS = 14
# Sustained per-second rates above these raise instance-health events. Small
# floors (not zero) so a single transient blip doesn't flap an alert.
DROP_EVENTS_PER_SEC = 1.0
SINK_FAIL_PER_SEC = 0.5


async def detect_and_record(db: AsyncSession) -> tuple[list[Event], list[Event]]:
    """Compute the current set of active conditions, then reconcile the open
    events table to match: insert newly-active conditions, resolve cleared ones.

    Returns ``(opened, resolved)`` — the events that *transitioned* this pass, so
    the caller can enqueue outbound notifications. Best-effort — never raises into
    the caller (a dashboard GET or the background worker)."""
    try:
        desired = await _desired_vector_version(db)
        active = await _active_conditions(db, desired)
        return await _reconcile(db, active)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"event detection failed: {e}")
        return [], []


async def _desired_vector_version(db: AsyncSession) -> str:
    from app.api.v1.settings import _get_setting

    general = await _get_setting("general", db)
    return str(general.get("desired_vector_version", "") or "")


async def _active_conditions(db: AsyncSession, desired: str) -> dict[str, dict]:
    """Return {dedup_key: event-fields} for every condition currently active."""
    now = datetime.now(timezone.utc)
    active: dict[str, dict] = {}

    instances = (
        (await db.execute(select(Instance).where(Instance.is_active.is_(True))))
        .scalars()
        .all()
    )
    # Per-fleet version override wins over the global default, so drift events
    # match what the dashboard/fleet view show (no false alarms on pinned fleets).
    from app.models.fleet import Fleet

    fleet_map = {f.id: f for f in (await db.execute(select(Fleet))).scalars().all()}
    # Live per-instance health (data loss / sink delivery) from VictoriaMetrics.
    vm = await fetch_fleet_metrics([hostname(i.api_url) for i in instances])
    for i in instances:
        fleet = fleet_map.get(i.fleet_id) if i.fleet_id else None
        eff_desired = effective_vector_version(fleet, desired)

        # Health signals — independent of agent/local mode (metrics-driven).
        m = vm.get(hostname(i.api_url), {})
        drops = m.get("discarded_per_sec", 0.0)
        sink_fail = m.get("sink_failed_per_sec", 0.0)
        if drops > DROP_EVENTS_PER_SEC:
            active[f"instance_dropping:{i.id}"] = {
                "kind": "instance_dropping",
                "severity": "critical",
                "title": f"{i.label} is dropping events",
                "body": f"~{round(drops)} events/s discarded "
                "(buffer overflow or sink failure) — data loss.",
                "resource_type": "instance",
                "resource_id": i.id,
            }
        elif sink_fail > SINK_FAIL_PER_SEC:
            active[f"instance_sink_failing:{i.id}"] = {
                "kind": "instance_sink_failing",
                "severity": "warning",
                "title": f"{i.label}: sink deliveries failing",
                "body": f"~{round(sink_fail, 1)} failed (4xx/5xx) responses/s.",
                "resource_type": "instance",
                "resource_id": i.id,
            }
        if i.config_push_mode == "agent":
            if is_agent_offline(i, now):
                active[f"instance_offline:{i.id}"] = {
                    "kind": "instance_offline",
                    "severity": "critical",
                    "title": f"{i.label} is offline",
                    "body": "Agent has not checked in.",
                    "resource_type": "instance",
                    "resource_id": i.id,
                }
            if i.agent_status == "validate_failed":
                active[f"agent_validate_failed:{i.id}"] = {
                    "kind": "agent_validate_failed",
                    "severity": "critical",
                    "title": f"{i.label}: config validation failed",
                    "body": None,
                    "resource_type": "instance",
                    "resource_id": i.id,
                }
            elif i.agent_status == "reload_failed":
                active[f"agent_reload_failed:{i.id}"] = {
                    "kind": "agent_reload_failed",
                    "severity": "critical",
                    "title": f"{i.label}: Vector reload failed",
                    "body": None,
                    "resource_type": "instance",
                    "resource_id": i.id,
                }
        if has_version_drift(i, eff_desired):
            active[f"vector_version_drift:{i.id}"] = {
                "kind": "vector_version_drift",
                "severity": "warning",
                "title": f"{i.label} on Vector {i.vector_version}",
                "body": f"Desired version is {eff_desired}.",
                "resource_type": "instance",
                "resource_id": i.id,
            }

    certs = (await db.execute(select(Certificate))).scalars().all()
    for c in certs:
        if c.expires_at is None:
            continue
        exp = c.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days = (exp - now).days
        if days <= CERT_EXPIRY_DAYS:
            active[f"cert_expiring:{c.id}"] = {
                "kind": "cert_expiring",
                "severity": "warning" if days > 0 else "critical",
                "title": f'Certificate "{c.label}" '
                + (f"expires in {days}d" if days > 0 else "has expired"),
                "body": None,
                "resource_type": "certificate",
                "resource_id": c.id,
            }

    return active


async def _reconcile(
    db: AsyncSession, active: dict[str, dict]
) -> tuple[list[Event], list[Event]]:
    open_events = (
        (await db.execute(select(Event).where(Event.resolved_at.is_(None))))
        .scalars()
        .all()
    )
    open_keys = {e.dedup_key for e in open_events}
    now = datetime.now(timezone.utc)
    opened: list[Event] = []
    resolved: list[Event] = []

    # Insert conditions that aren't already open. ON CONFLICT DO NOTHING guards
    # against a race between concurrent pollers (partial unique index). RETURNING
    # tells us which inserts actually happened — those are the real transitions.
    for key, fields in active.items():
        if key in open_keys:
            continue
        stmt = (
            pg_insert(Event)
            .values(dedup_key=key, **fields)
            .on_conflict_do_nothing(
                index_elements=[Event.dedup_key],
                index_where=Event.resolved_at.is_(None),
            )
            .returning(Event.id)
        )
        new_id = await db.scalar(stmt)
        if new_id:
            ev = await db.get(Event, new_id)
            if ev is not None:
                opened.append(ev)

    # Resolve open events whose condition has cleared.
    for e in open_events:
        if e.dedup_key not in active:
            e.resolved_at = now
            resolved.append(e)

    await db.commit()
    return opened, resolved
