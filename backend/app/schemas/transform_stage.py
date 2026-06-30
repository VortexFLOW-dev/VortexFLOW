# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TransformStageCreate(BaseModel):
    fleet_id: str
    name: str = Field(max_length=255)
    mode: str = "inline"  # inline | library
    source_vrl: Optional[str] = Field(default=None, max_length=131072)
    transform_id: Optional[str] = None
    inputs: list[str] = Field(default_factory=list, max_length=50)


class TransformStageUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    mode: Optional[str] = None
    source_vrl: Optional[str] = Field(default=None, max_length=131072)
    transform_id: Optional[str] = None
    inputs: Optional[list[str]] = Field(default=None, max_length=50)


class TransformStageResponse(BaseModel):
    id: str
    fleet_id: str
    name: str
    mode: str
    source_vrl: Optional[str]
    transform_id: Optional[str]
    inputs: list[str]
    created_at: datetime
    updated_at: datetime


class TransformStageListResponse(BaseModel):
    stages: list[TransformStageResponse]
    total: int
