# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import require_editor, require_viewer
from app.models.component import Component
from app.models.transform_stage import TransformStage
from app.models.route import Route
from app.models.fleet import Fleet
from app.models.user import User
from app.services import audit
from app.services.wiring import ensure_deletable
from app.schemas.route import (
    RouteCreate,
    RouteListResponse,
    RouteResponse,
    RouteUpdate,
)

router = APIRouter()


async def _get_route_or_404(route_id: str, db: AsyncSession) -> Route:
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


async def _validate_component_refs(
    fleet_id: str,
    source_ids: list[str],
    sink_ids: list[str],
    db: AsyncSession,
) -> None:
    """Ensure every referenced component exists and belongs to this fleet —
    prevents dangling refs and cross-fleet wiring. A route source may also be a
    remap stage (source → remap → route), so stage ids are valid too."""
    referenced = set(source_ids) | set(sink_ids)
    if not referenced:
        return
    result = await db.execute(
        select(Component.id).where(Component.fleet_id == fleet_id)
    )
    valid = {row[0] for row in result.all()}
    stage_result = await db.execute(
        select(TransformStage.id).where(TransformStage.fleet_id == fleet_id)
    )
    valid |= {row[0] for row in stage_result.all()}
    missing = referenced - valid
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown component(s) for this fleet: {', '.join(sorted(missing))}",
        )


@router.get("", response_model=RouteListResponse)
async def list_routes(
    fleet_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> RouteListResponse:
    q = select(Route).order_by(Route.created_at)
    if fleet_id:
        q = q.where(Route.fleet_id == fleet_id)
    result = await db.execute(q)
    routes = result.scalars().all()
    return RouteListResponse(
        routes=[RouteResponse.model_validate(r) for r in routes],
        total=len(routes),
    )


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_route(
    body: RouteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> RouteResponse:
    # Verify fleet exists
    fleet_result = await db.execute(select(Fleet).where(Fleet.id == body.fleet_id))
    if fleet_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Fleet not found")

    branch_sink_ids = [sid for b in body.branches for sid in b.sink_ids]
    await _validate_component_refs(
        body.fleet_id,
        body.source_ids,
        branch_sink_ids + body.passthrough_sink_ids,
        db,
    )

    route = Route(
        fleet_id=body.fleet_id,
        name=body.name,
        description=body.description,
        branches_json=json.dumps([b.model_dump() for b in body.branches]),
        source_ids_json=json.dumps(body.source_ids),
        passthrough_sink_ids_json=json.dumps(body.passthrough_sink_ids),
        created_by=current_user.id,
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return RouteResponse.model_validate(route)


@router.get("/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> RouteResponse:
    route = await _get_route_or_404(route_id, db)
    return RouteResponse.model_validate(route)


@router.patch("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    body: RouteUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> RouteResponse:
    route = await _get_route_or_404(route_id, db)

    # Validate any component refs being set against the route's fleet.
    branch_sink_ids = (
        [sid for b in body.branches for sid in b.sink_ids]
        if body.branches is not None
        else []
    )
    await _validate_component_refs(
        route.fleet_id,
        body.source_ids or [],
        branch_sink_ids + (body.passthrough_sink_ids or []),
        db,
    )

    if body.name is not None:
        route.name = body.name
    if body.description is not None:
        route.description = body.description
    if body.branches is not None:
        route.branches_json = json.dumps([b.model_dump() for b in body.branches])
    if body.source_ids is not None:
        route.source_ids_json = json.dumps(body.source_ids)
    if body.passthrough_sink_ids is not None:
        route.passthrough_sink_ids_json = json.dumps(body.passthrough_sink_ids)
    await db.commit()
    await db.refresh(route)
    return RouteResponse.model_validate(route)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> None:
    route = await _get_route_or_404(route_id, db)
    await ensure_deletable(route.fleet_id, route.id, force, db)
    name = route.name
    await db.delete(route)
    await db.commit()
    if force:
        await audit.record(
            action="route.delete_forced",
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type="route",
            resource_id=route_id,
            detail=f"force-deleted route '{name}' (had references)",
        )
