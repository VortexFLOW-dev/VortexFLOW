# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Resolve sibling references between a fleet's resources.

Components, transform stages, and routes are wired to each other by **id lists in
JSON columns** (``inputs_json``, ``source_ids_json``, branch ``sink_ids``,
``passthrough_sink_ids_json``), not foreign keys — so the database can't stop you
from deleting something another resource still points at. :func:`find_references`
computes that graph so delete endpoints can refuse (or warn) instead of silently
leaving a dangling reference that the renderer drops on the next deploy.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.component import Component
from app.models.route import Route
from app.models.transform_stage import TransformStage
from app.services.config_render import _json_list


async def find_references(
    fleet_id: str, target_id: str, db: AsyncSession
) -> list[dict[str, str]]:
    """Return the fleet resources whose wiring references ``target_id`` — i.e. what
    would dangle if it were deleted. Each entry is ``{kind, id, name}``.

    Matches an exact id, or (for a route target) an input of the form
    ``<target_id>.<branch>`` so a route's branch outputs count as references too.
    """
    refs: list[dict[str, str]] = []

    def _matches(ids: list[object]) -> bool:
        for i in ids:
            if i == target_id or (isinstance(i, str) and i.startswith(f"{target_id}.")):
                return True
        return False

    comps = (
        (await db.execute(select(Component).where(Component.fleet_id == fleet_id)))
        .scalars()
        .all()
    )
    for c in comps:
        if c.id != target_id and _matches(_json_list(c.inputs_json)):
            refs.append({"kind": c.kind, "id": c.id, "name": c.name})

    stages = (
        (
            await db.execute(
                select(TransformStage).where(TransformStage.fleet_id == fleet_id)
            )
        )
        .scalars()
        .all()
    )
    for s in stages:
        if s.id != target_id and _matches(_json_list(s.inputs_json)):
            refs.append({"kind": "transform", "id": s.id, "name": s.name})

    routes = (
        (await db.execute(select(Route).where(Route.fleet_id == fleet_id)))
        .scalars()
        .all()
    )
    for r in routes:
        if r.id == target_id:
            continue
        ids: list[object] = list(_json_list(r.source_ids_json))
        ids += list(_json_list(r.passthrough_sink_ids_json))
        for b in _json_list(r.branches_json):
            if isinstance(b, dict):
                ids += list(b.get("sink_ids", []) or [])
        if _matches(ids):
            refs.append({"kind": "route", "id": r.id, "name": r.name})

    return refs


async def ensure_deletable(
    fleet_id: str | None, target_id: str, force: bool, db: AsyncSession
) -> None:
    """Raise 409 if ``target_id`` is still referenced, unless ``force`` is set.

    The 409 ``detail`` carries the referencing resources so the UI can list them
    ("In use by Route 'fanout', Stage 'enrich'") and offer a force-delete.
    """
    if force or fleet_id is None:
        return
    refs = await find_references(fleet_id, target_id, db)
    if refs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "In use by "
                + ", ".join(f"{r['kind']} '{r['name']}'" for r in refs)
                + ". Unwire it first, or force-delete.",
                "references": refs,
            },
        )
