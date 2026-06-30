# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Unit tests for the fleet → Vector config renderer.

Focus: the listener bind-collision lint (`_bind_collisions`), which gates deploy.
Run from the backend dir: `pytest tests/test_config_render.py`.
"""

import json
import os
from types import SimpleNamespace

# Settings require a secret key at import time; set one before importing app code.
os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.services.config_render import (  # noqa: E402
    _split_host_port,
    render_fleet_config,
)


def _source(id_: str, name: str, ctype: str, cfg: dict) -> SimpleNamespace:
    """A minimal stand-in for a source Component (the renderer only reads attrs)."""
    return SimpleNamespace(
        id=id_,
        name=name,
        kind="source",
        component_type=ctype,
        config_json=json.dumps(cfg),
        inputs_json="[]",
    )


def test_split_host_port():
    assert _split_host_port("0.0.0.0:514") == ("0.0.0.0", "514")
    assert _split_host_port(":9000") == ("", "9000")
    assert _split_host_port("[::1]:514") == ("::1", "514")
    assert _split_host_port("127.0.0.1:8080") == ("127.0.0.1", "8080")
    # A unix socket path has no port — must not be treated as a listener.
    assert _split_host_port("/var/run/vector.sock") == ("/var/run/vector.sock", "")


def test_collision_same_wildcard_address():
    r = render_fleet_config(
        [
            _source(
                "a", "syslog A", "syslog", {"address": "0.0.0.0:514", "mode": "tcp"}
            ),
            _source(
                "b", "syslog B", "syslog", {"address": "0.0.0.0:514", "mode": "tcp"}
            ),
        ],
        [],
    )
    assert len(r.errors) == 1
    assert "514" in r.errors[0]


def test_collision_wildcard_overlaps_specific_host():
    # A wildcard bind (0.0.0.0) conflicts with any specific host on the same port.
    r = render_fleet_config(
        [
            _source("a", "A", "http_server", {"address": "0.0.0.0:8080"}),
            _source("b", "B", "http_server", {"address": "10.0.0.5:8080"}),
        ],
        [],
    )
    assert r.errors


def test_no_collision_different_protocol():
    # TCP and UDP can share a port — not a collision.
    r = render_fleet_config(
        [
            _source("a", "A", "syslog", {"address": "0.0.0.0:514", "mode": "tcp"}),
            _source("b", "B", "syslog", {"address": "0.0.0.0:514", "mode": "udp"}),
        ],
        [],
    )
    assert not r.errors


def test_no_collision_distinct_specific_hosts():
    r = render_fleet_config(
        [
            _source("a", "A", "http_server", {"address": "127.0.0.1:8080"}),
            _source("b", "B", "http_server", {"address": "127.0.0.2:8080"}),
        ],
        [],
    )
    assert not r.errors


def test_no_collision_distinct_ports():
    r = render_fleet_config(
        [
            _source("a", "A", "http_server", {"address": "0.0.0.0:8080"}),
            _source("b", "B", "http_server", {"address": "0.0.0.0:9090"}),
        ],
        [],
    )
    assert not r.errors


def test_no_collision_non_listeners():
    # Pull-based sources (file, etc.) have no `address` — never a bind collision.
    r = render_fleet_config(
        [
            _source("a", "A", "file", {"include": ["/var/log/*.log"]}),
            _source("b", "B", "file", {"include": ["/var/log/app/*.log"]}),
        ],
        [],
    )
    assert not r.errors
