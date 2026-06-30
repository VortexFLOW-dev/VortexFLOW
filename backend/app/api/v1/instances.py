# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_password_hash
from app.middleware.rbac import require_admin, require_viewer
from app.models.instance import Instance
from app.models.user import User
from app.schemas.instance import (
    InstanceCreate,
    InstanceHealth,
    InstanceResponse,
    InstanceUpdate,
)
from app.services import vector_client

router = APIRouter()


@router.get("", response_model=list[InstanceResponse])
async def list_instances(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> list[InstanceResponse]:
    result = await db.execute(select(Instance).order_by(Instance.created_at))
    return [InstanceResponse.model_validate(i) for i in result.scalars().all()]


# Declared before /{instance_id} so "fleet" isn't matched as an id.
@router.get("/fleet")
async def fleet(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> dict:
    """Enriched, live fleet view (status, version, config-sync, throughput) for
    the Instances console. Best-effort + VM-backed — see services/fleet_view."""
    from app.services.fleet_view import build_fleet

    return await build_fleet(db)


@router.post("", response_model=InstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_instance(
    body: InstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> InstanceResponse:
    instance = Instance(
        label=body.label,
        api_url=body.api_url,
        config_push_mode=body.config_push_mode,
        config_dir=body.config_dir,
        agent_url=body.agent_url,
        agent_token_hash=get_password_hash(body.agent_token)
        if body.agent_token
        else None,
        data_dir=body.data_dir,
        expire_metrics_secs=body.expire_metrics_secs,
        tls_verify=body.tls_verify,
        tls_ca_cert=body.tls_ca_cert,
        created_by=current_user.id,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return InstanceResponse.model_validate(instance)


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> InstanceResponse:
    instance = await _get_or_404(instance_id, db)
    return InstanceResponse.model_validate(instance)


@router.patch("/{instance_id}", response_model=InstanceResponse)
async def update_instance(
    instance_id: str,
    body: InstanceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> InstanceResponse:
    instance = await _get_or_404(instance_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "agent_token":
            instance.agent_token_hash = get_password_hash(value) if value else None
        else:
            setattr(instance, field, value)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return InstanceResponse.model_validate(instance)


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    instance = await _get_or_404(instance_id, db)
    await db.delete(instance)
    await db.commit()


@router.get("/{instance_id}/health", response_model=InstanceHealth)
async def instance_health(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> InstanceHealth:
    instance = await _get_or_404(instance_id, db)
    health = await vector_client.get_health(
        instance.api_url,
        tls_verify=instance.tls_verify,
        tls_ca_cert=instance.tls_ca_cert,
    )
    return InstanceHealth(instance_id=instance_id, **health)


@router.get("/{instance_id}/tap")
async def instance_tap(
    instance_id: str,
    component_id: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> StreamingResponse:
    """
    Stream live output events from a Vector component as Server-Sent Events.
    Proxies Vector's GraphQL subscription (graphql-ws) to the browser.
    """
    instance = await _get_or_404(instance_id, db)

    async def event_stream() -> object:
        try:
            async for event in vector_client.tap_component(
                instance.api_url,
                component_id,
                limit,
                tls_verify=instance.tls_verify,
                tls_ca_cert=instance.tls_ca_cert,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except vector_client.VectorClientError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )


@router.get("/{instance_id}/topology")
async def instance_topology(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> dict:
    instance = await _get_or_404(instance_id, db)
    try:
        return await vector_client.get_topology(instance.api_url)
    except vector_client.VectorClientError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


async def _get_or_404(instance_id: str, db: AsyncSession) -> Instance:
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found"
        )
    return instance
