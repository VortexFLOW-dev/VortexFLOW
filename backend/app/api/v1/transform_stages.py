# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Remap stage API — fleet-scoped VRL stages placed in the data path.

CRUD mirrors components/routes (editor-gated writes, viewer reads). A stage is
either inline VRL or a reference to a global vrl_transforms template; ``inputs``
names the upstream ids it reads.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import require_editor, require_viewer
from app.models.component import Component
from app.models.fleet import Fleet
from app.models.transform_stage import TransformStage
from app.models.user import User
from app.services import audit
from app.services.wiring import ensure_deletable
from app.models.vrl_transform import VrlTransform
from app.schemas.transform_stage import (
    TransformStageCreate,
    TransformStageListResponse,
    TransformStageResponse,
    TransformStageUpdate,
)

router = APIRouter()

_MODES = {"inline", "library"}


def _to_response(s: TransformStage) -> TransformStageResponse:
    try:
        inputs = json.loads(s.inputs_json or "[]")
    except json.JSONDecodeError:
        inputs = []
    return TransformStageResponse(
        id=s.id,
        fleet_id=s.fleet_id,
        name=s.name,
        mode=s.mode,
        source_vrl=s.source_vrl,
        transform_id=s.transform_id,
        inputs=inputs,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def _validate_mode(
    mode: str, source_vrl: str | None, transform_id: str | None, db: AsyncSession
) -> None:
    if mode not in _MODES:
        raise HTTPException(422, f"mode must be one of {sorted(_MODES)}")
    if mode == "library":
        if not transform_id:
            raise HTTPException(422, "library mode requires transform_id")
        ref = await db.get(VrlTransform, transform_id)
        if ref is None:
            raise HTTPException(422, "transform_id does not exist")
    elif mode == "inline" and not (source_vrl and source_vrl.strip()):
        raise HTTPException(422, "inline mode requires source_vrl")


async def _validate_inputs(
    fleet_id: str, inputs: list[str], db: AsyncSession, self_id: str | None = None
) -> None:
    """A stage may read this fleet's source components or other stages (not
    itself). Reject dangling/cross-fleet/self refs with a clear error rather than
    letting render silently drop them."""
    if not inputs:
        return
    valid: set[str] = set()
    comp_rows = await db.execute(
        select(Component.id).where(
            Component.fleet_id == fleet_id, Component.kind == "source"
        )
    )
    valid |= {r[0] for r in comp_rows}
    stage_rows = await db.execute(
        select(TransformStage.id).where(TransformStage.fleet_id == fleet_id)
    )
    valid |= {r[0] for r in stage_rows}
    if self_id:
        valid.discard(self_id)
    missing = set(inputs) - valid
    if missing:
        raise HTTPException(
            422, f"Invalid inputs for this fleet: {', '.join(sorted(missing))}"
        )


async def _get_or_404(stage_id: str, db: AsyncSession) -> TransformStage:
    stage = await db.get(TransformStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Transform stage not found")
    return stage


@router.get("", response_model=TransformStageListResponse)
async def list_stages(
    fleet_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> TransformStageListResponse:
    q = select(TransformStage).order_by(TransformStage.created_at)
    if fleet_id:
        q = q.where(TransformStage.fleet_id == fleet_id)
    stages = (await db.execute(q)).scalars().all()
    return TransformStageListResponse(
        stages=[_to_response(s) for s in stages], total=len(stages)
    )


@router.post(
    "", response_model=TransformStageResponse, status_code=status.HTTP_201_CREATED
)
async def create_stage(
    body: TransformStageCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> TransformStageResponse:
    if await db.get(Fleet, body.fleet_id) is None:
        raise HTTPException(status_code=404, detail="Fleet not found")
    await _validate_mode(body.mode, body.source_vrl, body.transform_id, db)
    await _validate_inputs(body.fleet_id, body.inputs, db)

    stage = TransformStage(
        fleet_id=body.fleet_id,
        name=body.name,
        mode=body.mode,
        source_vrl=body.source_vrl if body.mode == "inline" else None,
        transform_id=body.transform_id if body.mode == "library" else None,
        inputs_json=json.dumps(body.inputs),
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return _to_response(stage)


@router.patch("/{stage_id}", response_model=TransformStageResponse)
async def update_stage(
    stage_id: str,
    body: TransformStageUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> TransformStageResponse:
    stage = await _get_or_404(stage_id, db)
    data = body.model_dump(exclude_unset=True)

    new_mode = data.get("mode", stage.mode)
    new_vrl = data.get("source_vrl", stage.source_vrl)
    new_tid = data.get("transform_id", stage.transform_id)
    if "mode" in data or "source_vrl" in data or "transform_id" in data:
        await _validate_mode(new_mode, new_vrl, new_tid, db)

    if "name" in data:
        stage.name = data["name"]
    if "mode" in data:
        stage.mode = new_mode
    # Keep the off-mode field null so render never reads a stale value.
    if new_mode == "inline":
        if "source_vrl" in data:
            stage.source_vrl = new_vrl
        stage.transform_id = None
    else:
        if "transform_id" in data:
            stage.transform_id = new_tid
        stage.source_vrl = None
    if "inputs" in data and data["inputs"] is not None:
        await _validate_inputs(stage.fleet_id, data["inputs"], db, self_id=stage.id)
        stage.inputs_json = json.dumps(data["inputs"])

    await db.commit()
    await db.refresh(stage)
    return _to_response(stage)


@router.delete("/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage(
    stage_id: str,
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> None:
    stage = await _get_or_404(stage_id, db)
    await ensure_deletable(stage.fleet_id, stage.id, force, db)
    name = stage.name
    await db.delete(stage)
    await db.commit()
    if force:
        await audit.record(
            action="transform_stage.delete_forced",
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type="transform_stage",
            resource_id=stage_id,
            detail=f"force-deleted stage '{name}' (had references)",
        )
