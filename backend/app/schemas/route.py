# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator


def _parse_json_list(v: object) -> object:
    """Before-validator helper: decode a JSON-text column into a list."""
    if isinstance(v, str):
        try:
            raw = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        return raw
    return v


class RouteBranch(BaseModel):
    name: str = Field(..., max_length=100)
    condition: str = Field(..., max_length=2000)
    # Destination (sink) component ids this branch feeds.
    sink_ids: list[str] = Field(default_factory=list, max_length=50)


class RouteCreate(BaseModel):
    fleet_id: str
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    branches: list[RouteBranch] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    passthrough_sink_ids: list[str] = Field(default_factory=list, max_length=50)


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    branches: Optional[list[RouteBranch]] = Field(None, max_length=50)
    source_ids: Optional[list[str]] = Field(None, max_length=50)
    passthrough_sink_ids: Optional[list[str]] = Field(None, max_length=50)


class RouteResponse(BaseModel):
    id: str
    fleet_id: str
    name: str
    description: Optional[str]
    # ORM stores these as JSON text columns; accept either source.
    branches: list[RouteBranch] = Field(
        validation_alias=AliasChoices("branches", "branches_json"),
    )
    source_ids: list[str] = Field(
        validation_alias=AliasChoices("source_ids", "source_ids_json"),
    )
    passthrough_sink_ids: list[str] = Field(
        validation_alias=AliasChoices(
            "passthrough_sink_ids", "passthrough_sink_ids_json"
        ),
    )
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator("branches", "source_ids", "passthrough_sink_ids", mode="before")
    @classmethod
    def parse_json_list(cls, v: object) -> object:
        return _parse_json_list(v)


class RouteListResponse(BaseModel):
    routes: list[RouteResponse]
    total: int
