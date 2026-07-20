# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""MCP server unit tests (no DB / no network).

The full authenticated roundtrip (PAT auth + tool calls against a live client)
is exercised manually against a running backend; these cover the pure logic:
bearer extraction and the read-only tool surface.
"""

import asyncio

import pytest

from app.mcp.auth import McpAuthError, _extract_pat

# The v1 surface is read-only. This list is the guard: adding a write/deploy tool
# should be a deliberate change that updates this test (and the RBAC gating).
EXPECTED_TOOLS = [
    "get_catalog",
    "get_fleet",
    "list_components",
    "list_fleets",
    "list_instances",
    "list_routes",
    "list_transforms",
    "render_fleet_config",
    "validate_vrl",
]


class _Ctx:
    """Minimal stand-in for mcp.server.fastmcp.Context.request_context."""

    def __init__(self, headers=None, *, has_request=True):
        req = type("Req", (), {"headers": headers or {}})() if has_request else None
        self.request_context = type("RC", (), {"request": req})()


def test_extract_pat_ok():
    ctx = _Ctx({"authorization": "Bearer vf_pat_abc_def"})
    assert _extract_pat(ctx) == "vf_pat_abc_def"


def test_extract_pat_missing_header():
    with pytest.raises(McpAuthError):
        _extract_pat(_Ctx({}))


def test_extract_pat_wrong_scheme():
    with pytest.raises(McpAuthError):
        _extract_pat(_Ctx({"authorization": "Basic Zm9vOmJhcg=="}))


def test_extract_pat_empty_token():
    with pytest.raises(McpAuthError):
        _extract_pat(_Ctx({"authorization": "Bearer "}))


def test_extract_pat_no_http_request():
    # e.g. a non-HTTP transport — must not silently pass.
    with pytest.raises(McpAuthError):
        _extract_pat(_Ctx(has_request=False))


def test_tool_surface_is_read_only():
    from app.mcp.server import mcp

    names = sorted(t.name for t in asyncio.run(mcp.list_tools()))
    assert names == EXPECTED_TOOLS
