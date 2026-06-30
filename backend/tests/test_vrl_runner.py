# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Unit tests for the server-side VRL runner (`vector vrl`).

Focus: graceful degradation when the Vector binary isn't bundled (the dev-box
path), and the diagnostic cleaner. Run: `pytest tests/test_vrl_runner.py`.
"""

import asyncio
import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.core.config import settings  # noqa: E402
from app.services.vrl_runner import _clean, run_vrl  # noqa: E402


def test_clean_strips_ansi_and_caps():
    assert _clean("\x1b[31merror\x1b[0m here") == "error here"
    assert len(_clean("x" * 9000)) <= 4000


def test_clean_strips_vector_log_lines():
    raw = (
        '2026-06-23T13:27:20.442487Z  INFO vector::app: Log level is enabled. level="info"\n'
        "error[E105]: call to undefined function"
    )
    cleaned = _clean(raw)
    assert "Log level is enabled" not in cleaned
    assert "E105" in cleaned


def test_run_vrl_unavailable_without_binary(monkeypatch):
    # Point at a binary that does not exist → FileNotFoundError path.
    monkeypatch.setattr(settings, "vector_bin", "vortexflow-no-such-vector-bin")
    res = asyncio.run(run_vrl(". = .", {"a": 1}))
    assert res.ok is False
    assert res.source == "unavailable"
    assert "unavailable" in (res.error or "").lower()
    assert res.output is None
