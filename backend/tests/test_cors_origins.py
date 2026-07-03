# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""CORS origins are configurable; dev localhost origins ship only in debug — F13."""

import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.core.config import settings  # noqa: E402
from app.main import _cors_origins  # noqa: E402

DEV = {"http://localhost:5173", "http://localhost:3000"}


def _reset(monkeypatch, *, debug, public_url, cors):
    monkeypatch.setattr(settings, "debug", debug)
    monkeypatch.setattr(settings, "public_url", public_url)
    monkeypatch.setattr(settings, "cors_origins", cors)


def test_prod_ships_no_localhost_origins(monkeypatch):
    _reset(monkeypatch, debug=False, public_url="https://vf.example.com", cors="")
    origins = _cors_origins()
    assert origins == ["https://vf.example.com"]
    assert not (DEV & set(origins))


def test_debug_adds_localhost(monkeypatch):
    _reset(monkeypatch, debug=True, public_url=None, cors="")
    assert DEV <= set(_cors_origins())


def test_configured_origins_parsed_and_deduped(monkeypatch):
    _reset(
        monkeypatch,
        debug=False,
        public_url="https://vf.example.com",
        cors="https://ui.example.com, https://vf.example.com ,https://b.example.com",
    )
    origins = _cors_origins()
    assert origins == [
        "https://vf.example.com",
        "https://ui.example.com",
        "https://b.example.com",
    ]  # public_url first, whitespace trimmed, duplicate collapsed


def test_empty_when_nothing_configured(monkeypatch):
    _reset(monkeypatch, debug=False, public_url=None, cors="")
    assert _cors_origins() == []
