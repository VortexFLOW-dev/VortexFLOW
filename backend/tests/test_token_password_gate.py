# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A user under a forced password change must not mint a PAT (which inherits
their role) to bypass the gate — auth F11."""

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.api.v1.tokens import CreateTokenRequest, create_token  # noqa: E402


def _call(must_change):
    user = SimpleNamespace(
        id="u1", email="u@x.io", role="admin", must_change_password=must_change
    )
    body = CreateTokenRequest(name="ci")
    return asyncio.run(create_token(body=body, request=None, user=user, db=None))


def test_create_token_blocked_when_password_change_required():
    with pytest.raises(HTTPException) as ei:
        _call(must_change=True)
    assert ei.value.status_code == 403
    assert ei.value.detail == "password_change_required"
