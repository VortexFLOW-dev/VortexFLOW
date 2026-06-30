# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import ipaddress
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from datetime import datetime

# Loopback and link-local ranges must not be registered as agent api_url (SSRF).
# RFC1918 ranges are intentionally allowed — Vector agents live on private networks.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (cloud metadata)
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


class FleetCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class FleetUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    # Per-fleet Vector version target; "" / null = inherit the global default.
    desired_vector_version: Optional[str] = Field(None, max_length=50)


class FleetResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    is_default: bool
    generation: int = 0
    desired_vector_version: Optional[str] = None
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FleetListResponse(BaseModel):
    fleets: list[FleetResponse]
    total: int


class FleetBootstrapResponse(BaseModel):
    token: str


class AddInstanceToFleetRequest(BaseModel):
    role: str = Field(default="agent", pattern="^(agent|aggregator)$")


class InstanceInFleet(BaseModel):
    id: str
    label: str
    api_url: str
    role: str
    is_active: bool
    config_push_mode: str = "local"
    applied_generation: Optional[int] = None
    agent_last_seen: Optional[datetime] = None
    agent_status: Optional[str] = None

    model_config = {"from_attributes": True}


class RegisterAgentRequest(BaseModel):
    hostname: str = Field(..., max_length=253)
    api_url: str = Field(..., max_length=500)

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str) -> str:
        try:
            parsed = urlparse(v)
        except Exception:
            raise ValueError("Invalid URL")
        if parsed.scheme not in ("http", "https"):
            raise ValueError("api_url must use http or https")
        if not parsed.hostname:
            raise ValueError("api_url must include a hostname")
        # Reject loopback and link-local to prevent SSRF via cloud metadata endpoints
        try:
            addr = ipaddress.ip_address(parsed.hostname)
            for net in _BLOCKED_NETWORKS:
                if addr in net:
                    raise ValueError("api_url resolves to a blocked address range")
        except ValueError as exc:
            if "blocked address" in str(exc):
                raise
            # hostname is not a bare IP — DNS-resolved hostnames are accepted
        return v.rstrip("/")


class RegisterAgentResponse(BaseModel):
    id: str
    label: str
    fleet_id: str
    role: str
    # Long-lived per-agent token, returned once. The agent stores it and uses it
    # to authenticate config polls and status reports. Only the bcrypt hash is
    # persisted server-side.
    agent_token: str
