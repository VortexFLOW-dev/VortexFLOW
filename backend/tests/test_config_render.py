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


def _sink(
    id_: str, name: str, ctype: str, cfg: dict, inputs: list[str]
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        name=name,
        kind="sink",
        component_type=ctype,
        config_json=json.dumps(cfg),
        inputs_json=json.dumps(inputs),
    )


def test_config_type_key_cannot_clobber_allowlisted_type():
    # A source whose user config carries a `type` must NOT override the
    # allowlisted component_type (would defeat the create-time type allowlist).
    r = render_fleet_config(
        [_source("a", "src", "socket", {"type": "exec", "command": "id"})],
        [],
    )
    assert r.config["sources"]["src"]["type"] == "socket"
    assert "exec" not in json.dumps(r.config["sources"]["src"])
    assert any("reserved config key 'type'" in w for w in r.warnings)


def test_config_inputs_key_cannot_clobber_wiring():
    # A sink whose user config carries `inputs` must NOT override the wiring the
    # graph computed from inputs_json.
    r = render_fleet_config(
        [
            _source("a", "src", "socket", {"address": "0.0.0.0:514", "mode": "tcp"}),
            _sink("b", "dst", "console", {"inputs": ["evil"]}, inputs=["a"]),
        ],
        [],
    )
    assert r.config["sinks"]["dst"]["inputs"] == ["src"]
    assert any("reserved config key 'inputs'" in w for w in r.warnings)


def test_collect_secret_values_finds_revealed_secrets():
    from app.services.config_render import collect_secret_values

    cfg = {
        "sinks": {
            "s1": {
                "type": "http",
                "uri": "https://example.com",  # not secret
                "auth": {"password": "hunter2secret"},  # nested secret
                "token": "tok-abcdef123",  # secret
            }
        },
        "sources": {"a": {"type": "socket", "address": "0.0.0.0:514"}},
    }
    vals = collect_secret_values(cfg)
    assert "hunter2secret" in vals
    assert "tok-abcdef123" in vals
    assert "https://example.com" not in vals  # non-secret key preserved
    assert "0.0.0.0:514" not in vals


def test_collect_secret_values_skips_mask_but_keeps_short():
    from app.services.config_render import collect_secret_values
    from app.services.secrets import MASK

    # MASK/empty are excluded, but a SHORT real secret must still be collected
    # (no length floor) so it gets redacted from validator output.
    cfg = {"sinks": {"s": {"password": MASK, "token": "ab", "api_key": ""}}}
    assert collect_secret_values(cfg) == {"ab"}


def test_validate_redacts_secret_from_output(monkeypatch):
    # Even if `vector validate` echoes a secret value, validate_config must scrub
    # it before returning (svc F12). Fake the subprocess to emit the secret.
    # validate_config imports shutil/subprocess locally, so patch the real
    # modules (the function binds to the same module objects).
    import shutil
    import subprocess
    from types import SimpleNamespace

    from app.services.config_render import validate_config

    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/vector")

    def fake_run(*a, **k):
        return SimpleNamespace(
            returncode=1,
            stdout="error: invalid value 'hunter2secret' at auth.password",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = validate_config("noop: true\n", redact={"hunter2secret"})
    assert res.status == "invalid"
    assert "hunter2secret" not in res.output
    assert "«redacted-secret»" in res.output
