# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from app.core.netutil import validate_agent_api_url


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
        return validate_agent_api_url(v)


class RegisterAgentResponse(BaseModel):
    id: str
    label: str
    fleet_id: str
    role: str
    # Long-lived per-agent token, returned once. The agent stores it and uses it
    # to authenticate config polls and status reports. Only the bcrypt hash is
    # persisted server-side.
    agent_token: str
