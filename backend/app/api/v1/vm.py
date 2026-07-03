# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Authorization subrequest for the public /vm metrics-write proxy.

nginx gates ``/vm/api/v1/write`` with ``auth_request /_vm_authz`` → this endpoint.
It is a fast, DB-free bearer check so the metrics hot path stays cheap. When no
``metrics_write_token`` is configured the write path stays open (historical
behavior); when set, only a matching bearer is allowed, so anonymous callers can
no longer poison the metrics that drive health/alerting.
"""

import hmac

from fastapi import APIRouter, Header, Response, status

from app.core.config import settings

router = APIRouter()


@router.get("/authorize")
async def authorize_metrics_write(
    authorization: str | None = Header(default=None),
) -> Response:
    token = settings.metrics_write_token
    if not token:
        # Auth disabled — the write proxy is open (backward compatible).
        return Response(status_code=status.HTTP_200_OK)
    expected = f"Bearer {token}"
    if authorization and hmac.compare_digest(authorization, expected):
        return Response(status_code=status.HTTP_200_OK)
    return Response(status_code=status.HTTP_401_UNAUTHORIZED)
