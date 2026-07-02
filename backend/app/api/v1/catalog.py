# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Catalog schema API — serve the deployed Vector's `generate-schema` so the
frontend can build source/sink forms that match the running Vector version.

`GET /catalog/schema` returns the raw schema (any authenticated user); the Vector
version is in the `X-Vector-Version` header. `POST /catalog/refresh` (admin)
re-runs generate-schema. When Vector isn't bundled, /schema returns 503 and the
frontend falls back to its built-in catalog.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.netutil import client_ip
from app.middleware.auth import get_current_user
from app.middleware.rbac import require_admin
from app.models.user import User
from app.services import audit, catalog_schema

router = APIRouter()


def _client_ip(request: Request) -> str:
    return client_ip(request)


@router.get("/schema")
async def get_schema(
    _: User = Depends(get_current_user),
    force: bool = False,
) -> Response:
    raw = await catalog_schema.get_schema_json(force=force)
    if raw is None:
        return Response(
            content='{"detail":"Vector schema unavailable"}',
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    version = await catalog_schema.get_vector_version() or ""
    return Response(
        content=raw,
        media_type="application/json",
        headers={
            "X-Vector-Version": version,
            # Schema is large + changes only on image rebuild; let the browser cache.
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post("/refresh")
async def refresh_schema(
    request: Request,
    user: User = Depends(require_admin),
) -> dict:
    """Force a re-run of `vector generate-schema` (admin)."""
    catalog_schema.clear_cache()
    raw = await catalog_schema.get_schema_json(force=True)
    version = await catalog_schema.get_vector_version()
    await audit.record(
        action="catalog.refresh",
        user_id=user.id,
        user_email=user.email,
        ip=_client_ip(request),
        detail=f"vector={version}",
    )
    return {"available": raw is not None, "vector_version": version}
