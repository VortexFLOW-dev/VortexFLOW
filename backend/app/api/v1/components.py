# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.rbac import require_editor, require_viewer
from app.models.component import Component
from app.models.fleet import Fleet
from app.models.user import User
from app.services import audit
from app.services.wiring import ensure_deletable
from app.schemas.component import (
    ComponentCreate,
    ComponentListResponse,
    ComponentResponse,
    ComponentUpdate,
)
from app.services import secrets as secrets_svc

router = APIRouter()


def _to_response(component: Component) -> ComponentResponse:
    """Build a response with secrets masked — never return credentials to a
    client. config_json holds only non-secret fields; stored secrets surface as
    the MASK sentinel so the UI shows the field is set without revealing it."""
    public = json.loads(component.config_json or "{}")
    masked = secrets_svc.merge_masked(
        public, component.secrets_encrypted, settings.at_rest_key
    )
    resp = ComponentResponse.model_validate(component)
    resp.config = masked
    return resp


async def _get_component_or_404(component_id: str, db: AsyncSession) -> Component:
    result = await db.execute(select(Component).where(Component.id == component_id))
    component = result.scalar_one_or_none()
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return component


async def _validate_inputs(fleet_id: str, inputs: list[str], db: AsyncSession) -> None:
    """A sink's direct inputs must be same-fleet source components or remap
    stages (quick-connect / fan-out). Reject dangling/cross-fleet refs."""
    if not inputs:
        return
    from app.models.transform_stage import TransformStage

    valid: set[str] = set()
    src_rows = await db.execute(
        select(Component.id).where(
            Component.fleet_id == fleet_id, Component.kind == "source"
        )
    )
    valid |= {r[0] for r in src_rows}
    stage_rows = await db.execute(
        select(TransformStage.id).where(TransformStage.fleet_id == fleet_id)
    )
    valid |= {r[0] for r in stage_rows}
    missing = set(inputs) - valid
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid inputs for this fleet: {', '.join(sorted(missing))}",
        )


@router.get("", response_model=ComponentListResponse)
async def list_components(
    fleet_id: str | None = None,
    kind: str | None = Query(default=None, pattern="^(source|sink)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> ComponentListResponse:
    q = select(Component).order_by(Component.created_at)
    if fleet_id:
        q = q.where(Component.fleet_id == fleet_id)
    if kind:
        q = q.where(Component.kind == kind)
    result = await db.execute(q)
    components = result.scalars().all()
    return ComponentListResponse(
        components=[_to_response(c) for c in components],
        total=len(components),
    )


@router.post("", response_model=ComponentResponse, status_code=status.HTTP_201_CREATED)
async def create_component(
    body: ComponentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> ComponentResponse:
    fleet_result = await db.execute(select(Fleet).where(Fleet.id == body.fleet_id))
    if fleet_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Fleet not found")

    # Direct inputs are a sink-only concept (sources have none in Vector).
    sink_inputs = body.inputs if body.kind == "sink" else []
    if sink_inputs:
        await _validate_inputs(body.fleet_id, sink_inputs, db)

    try:
        public, secrets_enc = secrets_svc.split_for_write(
            body.config, None, settings.at_rest_key
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    component = Component(
        fleet_id=body.fleet_id,
        kind=body.kind,
        name=body.name,
        component_type=body.component_type,
        config_json=json.dumps(public),
        secrets_encrypted=secrets_enc,
        cert_refs_json=json.dumps(body.cert_refs) if body.cert_refs else None,
        inputs_json=json.dumps(sink_inputs),
        created_by=current_user.id,
    )
    db.add(component)
    await db.commit()
    await db.refresh(component)
    return _to_response(component)


@router.get("/{component_id}", response_model=ComponentResponse)
async def get_component(
    component_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> ComponentResponse:
    component = await _get_component_or_404(component_id, db)
    return _to_response(component)


@router.patch("/{component_id}", response_model=ComponentResponse)
async def update_component(
    component_id: str,
    body: ComponentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> ComponentResponse:
    component = await _get_component_or_404(component_id, db)
    if body.name is not None:
        component.name = body.name
    if body.config is not None:
        # Re-split: secret fields sent back as the MASK sentinel keep their
        # stored ciphertext; only changed/new secrets are re-encrypted.
        try:
            public, secrets_enc = secrets_svc.split_for_write(
                body.config, component.secrets_encrypted, settings.at_rest_key
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        component.config_json = json.dumps(public)
        component.secrets_encrypted = secrets_enc
    if body.inputs is not None and component.kind == "sink":
        await _validate_inputs(component.fleet_id, body.inputs, db)
        component.inputs_json = json.dumps(body.inputs)
    if body.cert_refs is not None:
        component.cert_refs_json = (
            json.dumps(body.cert_refs) if body.cert_refs else None
        )
    await db.commit()
    await db.refresh(component)
    return _to_response(component)


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_component(
    component_id: str,
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> None:
    component = await _get_component_or_404(component_id, db)
    await ensure_deletable(component.fleet_id, component.id, force, db)
    name, kind = component.name, component.kind
    await db.delete(component)
    await db.commit()
    if force:
        await audit.record(
            action="component.delete_forced",
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type="component",
            resource_id=component_id,
            detail=f"force-deleted {kind} '{name}' (had references)",
        )
