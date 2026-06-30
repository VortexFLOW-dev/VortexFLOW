# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for component TLS cert-ref rendering (config_render + cert delivery)."""

import json
from types import SimpleNamespace

from app.services.config_render import COMPONENT_CERTS_DIR, render_fleet_config


def _sink(**kw):
    base = dict(
        id="s1",
        kind="sink",
        name="es",
        component_type="elasticsearch",
        config_json='{"endpoint": "https://es:9200"}',
        secrets_encrypted=None,
        cert_refs_json=None,
        inputs_json="[]",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_cert_refs_revealed_emits_files_and_paths():
    c = _sink(id="abc", cert_refs_json=json.dumps({"identity": "id1", "ca": "ca1"}))
    mats = {
        "id1": {"cert_pem": "CERTPEM", "key_pem": "KEYPEM", "passphrase": "PW"},
        "ca1": {"cert_pem": "CACERT", "ca_chain_pem": "CACHAIN"},
    }
    r = render_fleet_config([c], [], reveal_secrets=True, cert_materials=mats)
    base = f"{COMPONENT_CERTS_DIR}/abc"
    tls = r.config["sinks"]["es"]["tls"]
    assert tls["crt_file"] == f"{base}/crt.pem"
    assert tls["key_file"] == f"{base}/key.pem"
    assert tls["ca_file"] == f"{base}/ca.pem"
    assert tls["key_pass"] == "PW"

    by_path = {f["path"]: f for f in r.files}
    assert by_path[f"{base}/crt.pem"]["content"] == "CERTPEM"
    assert by_path[f"{base}/crt.pem"]["mode"] == 0o644
    assert by_path[f"{base}/key.pem"]["content"] == "KEYPEM"
    assert by_path[f"{base}/key.pem"]["mode"] == 0o600  # key locked down
    assert by_path[f"{base}/ca.pem"]["content"] == "CACHAIN"  # prefers chain over leaf


def test_cert_refs_masked_rewrites_paths_no_files():
    c = _sink(id="abc", cert_refs_json=json.dumps({"identity": "id1"}))
    r = render_fleet_config([c], [], reveal_secrets=False, cert_materials=None)
    base = f"{COMPONENT_CERTS_DIR}/abc"
    tls = r.config["sinks"]["es"]["tls"]
    # Preview rewrites the paths (so the user sees the managed location) but
    # never emits cert material or the passphrase.
    assert tls["crt_file"] == f"{base}/crt.pem"
    assert tls["key_file"] == f"{base}/key.pem"
    assert "key_pass" not in tls
    assert r.files == []


def test_no_cert_refs_leaves_config_untouched():
    r = render_fleet_config([_sink()], [], reveal_secrets=True, cert_materials={})
    assert r.files == []
    assert "tls" not in r.config["sinks"]["es"]


def test_missing_material_warns_and_emits_no_file():
    c = _sink(id="abc", cert_refs_json=json.dumps({"identity": "missing"}))
    r = render_fleet_config([c], [], reveal_secrets=True, cert_materials={})
    assert any("certificate not found" in w for w in r.warnings)
    assert r.files == []
    # Path is still rewritten so the config is internally consistent.
    assert (
        r.config["sinks"]["es"]["tls"]["crt_file"]
        == f"{COMPONENT_CERTS_DIR}/abc/crt.pem"
    )
