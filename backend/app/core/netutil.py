# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from fastapi import Request

from app.core.config import settings


def client_ip(request: Request) -> str:
    """Resolve the real client IP from X-Forwarded-For, honouring the configured
    number of trusted reverse proxies.

    With ``trusted_proxy_count`` proxies in front, the trustworthy client IP is
    the Nth value from the right of XFF (each trusted proxy appends the address
    it observed). Reading from the right means a client-supplied, spoofed XFF
    prefix cannot forge the result. Set ``trusted_proxy_count = 0`` to ignore XFF
    entirely for a directly-exposed deployment.
    """
    n = settings.trusted_proxy_count
    fwd = request.headers.get("X-Forwarded-For")
    if fwd and n > 0:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if len(parts) >= n:
            return parts[-n]
    return request.client.host if request.client else "unknown"
