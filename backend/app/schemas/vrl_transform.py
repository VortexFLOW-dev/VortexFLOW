# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from datetime import datetime

_MAX_VRL_BYTES = 65_536
_MAX_EVENT_BYTES = 65_536


class VrlTransformCreate(BaseModel):
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1024)
    source_vrl: str = Field(max_length=_MAX_VRL_BYTES)


class VrlTransformUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1024)
    source_vrl: Optional[str] = Field(default=None, max_length=_MAX_VRL_BYTES)


class VrlTransformResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    source_vrl: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VrlTransformListResponse(BaseModel):
    transforms: list[VrlTransformResponse]
    total: int


class VrlTestRequest(BaseModel):
    vrl: str = Field(max_length=_MAX_VRL_BYTES)
    event: dict[str, Any] = {}
    instance_id: Optional[str] = None

    @field_validator("event")
    @classmethod
    def event_size_limit(cls, v: dict) -> dict:
        if len(json.dumps(v)) > _MAX_EVENT_BYTES:
            raise ValueError(
                f"event payload must not exceed {_MAX_EVENT_BYTES} bytes when serialized"
            )
        return v


class VrlTestResponse(BaseModel):
    success: bool
    output: Optional[dict] = None
    error: Optional[str] = None
    instance_id: Optional[str] = None


class VrlValidateRequest(BaseModel):
    """Validate/run VRL with the bundled `vector` binary — no instance required."""

    vrl: str = Field(max_length=_MAX_VRL_BYTES)
    event: dict[str, Any] = {}

    @field_validator("event")
    @classmethod
    def event_size_limit(cls, v: dict) -> dict:
        if len(json.dumps(v)) > _MAX_EVENT_BYTES:
            raise ValueError(
                f"event payload must not exceed {_MAX_EVENT_BYTES} bytes when serialized"
            )
        return v


class VrlValidateResponse(BaseModel):
    ok: bool
    output: Optional[dict] = None
    error: Optional[str] = None
    source: str = "vector-cli"  # "vector-cli" | "unavailable"
