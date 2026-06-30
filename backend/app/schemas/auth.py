# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthMethodsResponse(BaseModel):
    local: bool = True
    azure: bool = False
    oidc: bool = False
    oidc_display_name: str = "SSO"
    saml: bool = False
    saml_display_name: str = "SAML SSO"
    ldap: bool = False
    # Configurable brand name (Settings → General). Public so the login page and
    # app shell can render it pre-auth.
    app_name: str = "VortexFlow"


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    auth_method: str
    must_change_password: bool = False

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RecoveryRequest(BaseModel):
    token: str
    new_password: str


class RecoveryStatusResponse(BaseModel):
    available: bool
