# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.database import get_db
from app.middleware.rbac import require_editor, require_viewer
from app.models.instance import Instance
from app.models.user import User
from app.models.vrl_transform import VrlTransform
from app.schemas.vrl_transform import (
    VrlTestRequest,
    VrlTestResponse,
    VrlTransformCreate,
    VrlTransformListResponse,
    VrlTransformResponse,
    VrlTransformUpdate,
    VrlValidateRequest,
    VrlValidateResponse,
)
from app.services import ai_config, ai_generate, audit
from app.services.redis_client import check_rate_limit
from app.services.vrl_runner import run_vrl

logger = logging.getLogger(__name__)
router = APIRouter()

# Vector GraphQL mutation for VRL testing (available since Vector 0.38)
_TEST_REMAP_MUTATION = """
mutation TestRemap($program: String!, $event: String!) {
  testRemap(program: $program, event: $event) {
    success
    output
    error
  }
}
"""

_TEST_RATE_LIMIT = 60  # requests per minute per user
# AI generation is an outbound LLM call — tighter cap to bound cost + egress.
_AI_GENERATE_RATE_LIMIT = 20  # requests per minute per user


@router.get("", response_model=VrlTransformListResponse)
async def list_transforms(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> VrlTransformListResponse:
    result = await db.execute(select(VrlTransform).order_by(VrlTransform.name))
    transforms = result.scalars().all()
    return VrlTransformListResponse(
        transforms=[VrlTransformResponse.model_validate(t) for t in transforms],
        total=len(transforms),
    )


@router.post(
    "", response_model=VrlTransformResponse, status_code=status.HTTP_201_CREATED
)
async def create_transform(
    body: VrlTransformCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> VrlTransformResponse:
    transform = VrlTransform(
        name=body.name,
        description=body.description,
        source_vrl=body.source_vrl,
        created_by=current_user.id,
    )
    db.add(transform)
    await db.commit()
    await db.refresh(transform)
    return VrlTransformResponse.model_validate(transform)


@router.post("/test", response_model=VrlTestResponse)
async def test_vrl(
    body: VrlTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_viewer),
) -> VrlTestResponse:
    allowed = await check_rate_limit(
        f"vrl_test_rate:{current_user.id}", _TEST_RATE_LIMIT
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="VRL test rate limit exceeded. Maximum 60 requests per minute.",
        )

    instance, not_found = await _pick_instance(body.instance_id, db)
    if instance is None:
        if not_found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance '{body.instance_id}' not found.",
            )
        return VrlTestResponse(
            success=False,
            error="No reachable Vector instance available for VRL testing. "
            "Add an instance and ensure it is online.",
        )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0)
        ) as client:
            r = await client.post(
                f"{instance.api_url}/graphql",
                json={
                    "query": _TEST_REMAP_MUTATION,
                    "variables": {
                        "program": body.vrl,
                        "event": json.dumps(body.event),
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            gql = r.json()

        if "errors" in gql:
            return VrlTestResponse(
                success=False,
                error=gql["errors"][0].get("message", "GraphQL error"),
                instance_id=instance.id,
            )

        result = gql.get("data", {}).get("testRemap", {})
        if result.get("success"):
            raw_output = result.get("output", "{}")
            try:
                output = (
                    json.loads(raw_output)
                    if isinstance(raw_output, str)
                    else raw_output
                )
            except json.JSONDecodeError:
                output = {"raw": raw_output}
            return VrlTestResponse(success=True, output=output, instance_id=instance.id)
        else:
            return VrlTestResponse(
                success=False,
                error=result.get("error", "VRL execution failed"),
                instance_id=instance.id,
            )

    except httpx.ConnectError:
        return VrlTestResponse(
            success=False,
            error=f"Cannot connect to Vector at {instance.api_url}",
            instance_id=instance.id,
        )
    except httpx.TimeoutException:
        return VrlTestResponse(
            success=False,
            error=f"Vector at {instance.api_url} timed out. The VRL program may be too complex.",
            instance_id=instance.id,
        )
    except Exception:
        logger.exception(
            "Unexpected error during VRL test for instance %s", instance.id
        )
        return VrlTestResponse(
            success=False,
            error="An unexpected error occurred. Check server logs for details.",
            instance_id=instance.id,
        )


@router.post("/validate", response_model=VrlValidateResponse)
async def validate_vrl(
    body: VrlValidateRequest,
    current_user: User = Depends(require_viewer),
) -> VrlValidateResponse:
    """Compile/run VRL against a sample event using the bundled `vector` binary.

    Needs no Vector instance (the editor's instant compile-check). Returns the
    transformed event on success, or Vector's diagnostic on a compile/runtime error.
    """
    allowed = await check_rate_limit(
        f"vrl_validate_rate:{current_user.id}", _TEST_RATE_LIMIT
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="VRL validate rate limit exceeded. Maximum 60 requests per minute.",
        )

    result = await run_vrl(body.vrl, body.event)
    return VrlValidateResponse(
        ok=result.ok,
        output=result.output,
        error=result.error,
        source=result.source,
    )


# ─── AI VRL generation (VRL/AI plan B3) ──────────────────────────────────────


class AiStatusResponse(BaseModel):
    enabled: bool
    provider: str


@router.get("/ai/status", response_model=AiStatusResponse)
async def ai_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> AiStatusResponse:
    """Editor-readable enabled flag for UI gating (no secrets). The full config
    (`GET /settings/ai`) stays admin-only; editors only learn on/off + provider."""
    raw = await ai_config.load_raw(db)
    return AiStatusResponse(
        enabled=bool(raw.get("enabled")),
        provider=raw.get("provider", "anthropic"),
    )


class AiGenerateRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=2000)
    event: dict
    current_vrl: str = Field(default="", max_length=20000)
    max_retries: int = Field(default=3, ge=1, le=3)


class AiGenerateResponse(BaseModel):
    ok: bool
    vrl: str
    before: dict | None = None
    after: dict | None = None
    attempts: int
    error: str | None = None
    source: str


@router.post("/ai/generate", response_model=AiGenerateResponse)
async def ai_generate_vrl(
    body: AiGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_editor),
) -> AiGenerateResponse:
    """Generate *validated* VRL from intent + a sample event (BYO-LLM).

    Generate → compile with the bundled `vector` binary → on error, feed the
    diagnostic back and regenerate (bounded). Configured `redact_fields` are
    stripped from the sample BEFORE it reaches the model; validation runs on the
    original event. AI-authored, audit-logged.
    """
    allowed = await check_rate_limit(
        f"vrl_ai_generate_rate:{current_user.id}", _AI_GENERATE_RATE_LIMIT
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI generate rate limit exceeded. Maximum 20 requests per minute.",
        )

    if len(json.dumps(body.event, default=str)) > ai_generate.MAX_EVENT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sample event is too large to send to the model.",
        )

    raw = await ai_config.load_raw(db)
    if not raw.get("enabled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The AI assistant is disabled. Enable it in Settings → AI.",
        )

    result = await ai_generate.generate(
        raw=raw,
        secret_key=app_settings.at_rest_key,
        intent=body.intent,
        event=body.event,
        current_vrl=body.current_vrl,
        max_retries=body.max_retries,
    )
    await audit.record(
        action="transform.ai_generate",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="transform",
        detail=(
            f"provider={raw.get('provider')} ok={result.ok} attempts={result.attempts}"
        ),
    )
    return AiGenerateResponse(
        ok=result.ok,
        vrl=result.vrl,
        before=result.before,
        after=result.after,
        attempts=result.attempts,
        error=result.error,
        source=result.source,
    )


@router.get("/{transform_id}", response_model=VrlTransformResponse)
async def get_transform(
    transform_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> VrlTransformResponse:
    transform = await _get_or_404(transform_id, db)
    return VrlTransformResponse.model_validate(transform)


@router.patch("/{transform_id}", response_model=VrlTransformResponse)
async def update_transform(
    transform_id: str,
    body: VrlTransformUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> VrlTransformResponse:
    transform = await _get_or_404(transform_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(transform, field, value)
    db.add(transform)
    await db.commit()
    await db.refresh(transform)
    return VrlTransformResponse.model_validate(transform)


@router.delete("/{transform_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transform(
    transform_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> None:
    transform = await _get_or_404(transform_id, db)
    await db.delete(transform)
    await db.commit()


async def _pick_instance(
    instance_id: str | None, db: AsyncSession
) -> tuple[Instance | None, bool]:
    """Return (instance, not_found_flag). not_found_flag is True only when an explicit
    instance_id was provided but matched no record."""
    if instance_id:
        result = await db.execute(
            select(Instance).where(
                Instance.id == instance_id,
                Instance.is_active == True,  # noqa: E712
            )
        )
        inst = result.scalar_one_or_none()
        return (inst, inst is None)
    # Fall back to first active instance
    result = await db.execute(
        select(Instance)
        .where(Instance.is_active == True)  # noqa: E712
        .order_by(Instance.created_at)
        .limit(1)
    )
    return (result.scalar_one_or_none(), False)


async def _get_or_404(transform_id: str, db: AsyncSession) -> VrlTransform:
    result = await db.execute(
        select(VrlTransform).where(VrlTransform.id == transform_id)
    )
    transform = result.scalar_one_or_none()
    if not transform:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transform not found"
        )
    return transform
