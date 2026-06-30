# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared fleet status + enrichment — the single source of truth for "how is
this instance doing", consumed by the Instances fleet console, the dashboard,
and (for its thresholds) the event detector.

Status is **mode-aware**: agent-mode instances heartbeat (we have last-seen,
agent_status, applied generation), while local-mode instances never call home —
their liveness is inferred best-effort from whether Vector is emitting metrics.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import Instance
from app.models.fleet import Fleet
from app.services.vm_metrics import fetch_fleet_metrics

# An agent-mode instance is offline if it hasn't checked in within this window
# (the agent polls config + posts status well under this). Single source of the
# threshold — the event detector imports it from here.
AGENT_OFFLINE_AFTER = timedelta(minutes=3)


@dataclass
class Status:
    state: str  # healthy | degraded | offline | unknown | inactive
    reason: str


def hostname(api_url: str) -> str:
    """Extract hostname from a URL, falling back to the raw string."""
    try:
        return urlparse(api_url).hostname or api_url
    except Exception:
        return api_url


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_agent_offline(instance: Instance, now: datetime) -> bool:
    """Agent-mode only: True if the agent hasn't checked in within the window."""
    last = _aware(instance.agent_last_seen)
    return last is None or (now - last) > AGENT_OFFLINE_AFTER


def has_version_drift(instance: Instance, desired_version: str) -> bool:
    return bool(
        desired_version
        and instance.vector_version
        and instance.vector_version != desired_version
    )


def effective_vector_version(fleet, global_default: str) -> str:
    """Resolve the desired Vector version for a fleet's members: the per-fleet
    override wins, else the global default. Empty/None override = inherit global.
    Single source of truth so the agent endpoint, dashboard, fleet view, and
    event detector can't drift apart."""
    override = getattr(fleet, "desired_vector_version", None) if fleet else None
    return str(override or global_default or "")


def derive_status(
    instance: Instance,
    fleet_generation: Optional[int],
    desired_version: str,
    now: datetime,
    has_metrics: bool,
) -> Status:
    """Roll a single instance up to one status + human reason."""
    if not instance.is_active:
        return Status("inactive", "Administratively disabled")

    drift = has_version_drift(instance, desired_version)

    if instance.config_push_mode == "agent":
        if is_agent_offline(instance, now):
            return Status("offline", "No agent check-in")
        if instance.agent_status == "validate_failed":
            return Status("degraded", "Config validation failed")
        if instance.agent_status == "reload_failed":
            return Status("degraded", "Vector reload failed")
        if fleet_generation is not None:
            if instance.applied_generation is None:
                return Status("degraded", "Awaiting first config apply")
            if instance.applied_generation < fleet_generation:
                return Status(
                    "degraded",
                    f"Config out of date (applied {instance.applied_generation}"
                    f" < {fleet_generation})",
                )
        if drift:
            return Status(
                "degraded",
                f"Vector {instance.vector_version} (desired {desired_version})",
            )
        return Status("healthy", "Checked in and converged")

    # local mode — no heartbeat; liveness is best-effort from metrics.
    if drift:
        return Status(
            "degraded", f"Vector {instance.vector_version} (desired {desired_version})"
        )
    if has_metrics:
        return Status("healthy", "Reporting metrics")
    return Status("unknown", "No recent metrics (local mode)")


async def build_fleet(db: AsyncSession) -> dict:
    """Enriched, live, best-effort view of every instance — the payload behind
    GET /instances/fleet. VM-backed; degrades gracefully if VM is unreachable."""
    from app.api.v1.settings import _get_setting

    now = datetime.now(timezone.utc)
    general = await _get_setting("general", db)
    desired = str(general.get("desired_vector_version", "") or "")

    instances = (
        (await db.execute(select(Instance).order_by(Instance.created_at)))
        .scalars()
        .all()
    )
    fleets = (await db.execute(select(Fleet))).scalars().all()
    fleet_map = {s.id: s for s in fleets}

    hostnames = list({hostname(i.api_url) for i in instances if i.api_url})
    vm = await fetch_fleet_metrics(hostnames)

    out_instances = []
    for i in instances:
        host = hostname(i.api_url)
        metrics = vm.get(
            host,
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
        fleet = fleet_map.get(i.fleet_id) if i.fleet_id else None
        fleet_gen = fleet.generation if fleet else None
        eff_desired = effective_vector_version(fleet, desired)
        status = derive_status(i, fleet_gen, eff_desired, now, has_metrics)

        # Config convergence only meaningful for agent-mode members of a fleet.
        config_synced: Optional[bool] = None
        if i.config_push_mode == "agent" and fleet_gen is not None:
            config_synced = i.applied_generation == fleet_gen

        last_seen = _aware(i.agent_last_seen)
        out_instances.append(
            {
                "id": i.id,
                "label": i.label,
                "api_url": i.api_url,
                "host": host,
                "config_push_mode": i.config_push_mode,
                "role": i.role,
                "fleet_id": i.fleet_id,
                "is_active": i.is_active,
                "vector_version": i.vector_version,
                "version_drift": has_version_drift(i, eff_desired),
                "agent_status": i.agent_status,
                "agent_last_seen": last_seen.isoformat() if last_seen else None,
                "fleet_generation": fleet_gen,
                "applied_generation": i.applied_generation,
                "config_synced": config_synced,
                "status": {"state": status.state, "reason": status.reason},
                "metrics": metrics,
            }
        )

    return {
        "instances": out_instances,
        "fleets": {
            s.id: {
                "name": s.name,
                "generation": s.generation,
                "is_default": s.is_default,
                # Per-fleet override (empty = inherits the global default).
                "desired_vector_version": s.desired_vector_version or "",
                "effective_vector_version": effective_vector_version(s, desired),
            }
            for s in fleets
        },
        "desired_vector_version": desired,
    }
