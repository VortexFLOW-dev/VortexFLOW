# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""nginx auth_request gate for the /vm metrics-write proxy (ADR-001)."""

import asyncio
import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.api.v1.vm import authorize_metrics_write  # noqa: E402
from app.core.config import settings  # noqa: E402


def _call(auth):
    return asyncio.run(authorize_metrics_write(authorization=auth)).status_code


def test_open_when_no_token(monkeypatch):
    monkeypatch.setattr(settings, "metrics_write_token", None)
    assert _call(None) == 200
    assert _call("Bearer anything") == 200


def test_requires_matching_bearer_when_set(monkeypatch):
    monkeypatch.setattr(settings, "metrics_write_token", "s3cr3t-token")
    assert _call("Bearer s3cr3t-token") == 200
    assert _call("Bearer wrong") == 401
    assert _call(None) == 401
    assert _call("s3cr3t-token") == 401  # missing "Bearer " prefix
