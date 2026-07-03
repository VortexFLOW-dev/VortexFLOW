# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""check_rate_limit degradation is configurable (fail open vs closed) — auth F14."""

import asyncio
import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.core.config import settings  # noqa: E402
from app.services import redis_client  # noqa: E402


def _rl(monkeypatch, *, fail_closed):
    # Simulate Redis unreachable: _get() returns None.
    async def _none():
        return None

    monkeypatch.setattr(redis_client, "_get", _none)
    monkeypatch.setattr(settings, "rate_limit_fail_closed", fail_closed)
    return asyncio.run(redis_client.check_rate_limit("k", 5))


def test_fail_open_default_allows(monkeypatch):
    assert _rl(monkeypatch, fail_closed=False) is True


def test_fail_closed_denies(monkeypatch):
    assert _rl(monkeypatch, fail_closed=False) is True
    assert _rl(monkeypatch, fail_closed=True) is False
