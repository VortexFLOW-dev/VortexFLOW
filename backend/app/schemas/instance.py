# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional
from pydantic import BaseModel, field_validator
from datetime import datetime


class InstanceCreate(BaseModel):
    label: str
    api_url: str
    config_push_mode: str = "local"
    config_dir: Optional[str] = None
    agent_url: Optional[str] = None
    agent_token: Optional[str] = None  # plaintext — hashed before storage
    data_dir: Optional[str] = None
    expire_metrics_secs: Optional[int] = None
    tls_verify: bool = True
    tls_ca_cert: Optional[str] = None

    @field_validator("config_push_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("local", "agent"):
            raise ValueError("config_push_mode must be 'local' or 'agent'")
        return v

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("api_url must start with http:// or https://")
        return v.rstrip("/")


class InstanceUpdate(BaseModel):
    label: Optional[str] = None
    api_url: Optional[str] = None
    config_push_mode: Optional[str] = None
    config_dir: Optional[str] = None
    agent_url: Optional[str] = None
    agent_token: Optional[str] = None
    data_dir: Optional[str] = None
    expire_metrics_secs: Optional[int] = None
    is_active: Optional[bool] = None
    tls_verify: Optional[bool] = None
    tls_ca_cert: Optional[str] = None

    @field_validator("config_push_mode")
    @classmethod
    def validate_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("local", "agent"):
            raise ValueError("config_push_mode must be 'local' or 'agent'")
        return v


class InstanceResponse(BaseModel):
    id: str
    label: str
    api_url: str
    config_push_mode: str
    config_dir: Optional[str]
    agent_url: Optional[str]
    data_dir: Optional[str] = None
    expire_metrics_secs: Optional[int] = None
    is_active: bool
    fleet_id: Optional[str] = None
    role: str = "agent"
    tls_verify: bool = True
    tls_ca_cert: Optional[str] = None
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstanceHealth(BaseModel):
    instance_id: str
    reachable: bool
    vector_version: Optional[str] = None
    uptime_seconds: Optional[float] = None
    error: Optional[str] = None
