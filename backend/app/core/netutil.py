# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import ipaddress
from urllib.parse import urlparse

from fastapi import Request

from app.core.config import settings

# Loopback and link-local ranges must not be reachable via a registered agent /
# instance api_url — the server makes outbound calls to it (health checks, agent
# reachability), so an internal literal is an SSRF vector (esp. 169.254.169.254
# cloud metadata). RFC1918 ranges are intentionally allowed — Vector agents and
# instances legitimately live on private networks.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (cloud metadata)
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def validate_agent_api_url(v: str) -> str:
    """Validate an agent/instance ``api_url`` and normalise it (strip trailing
    ``/``). Requires http(s) + a hostname and rejects loopback / link-local IP
    literals to prevent SSRF via the server's outbound calls. A DNS hostname is
    accepted as-is (not resolved here); RFC1918 targets are allowed by design."""
    try:
        parsed = urlparse(v)
    except Exception:
        raise ValueError("Invalid URL")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("api_url must use http or https")
    if not parsed.hostname:
        raise ValueError("api_url must include a hostname")
    try:
        addr = ipaddress.ip_address(parsed.hostname)
        for net in _BLOCKED_NETWORKS:
            if addr in net:
                raise ValueError("api_url resolves to a blocked address range")
    except ValueError as exc:
        if "blocked address" in str(exc):
            raise
        # hostname is not a bare IP literal — DNS hostnames are accepted
    return v.rstrip("/")


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
