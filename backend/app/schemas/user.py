# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    auth_method: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    role: str = "viewer"
    password: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int


class ResetPasswordRequest(BaseModel):
    # Optional — if omitted, the server generates one and returns it once.
    new_password: Optional[str] = None


class ResetPasswordResponse(BaseModel):
    # The plaintext password is only returned when the server generated it.
    generated: bool
    password: Optional[str] = None
