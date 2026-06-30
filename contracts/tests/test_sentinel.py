# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Drift-injection tests — prove each check FAILS when (and only when) it should.

Checks call their adapters as `sources.<fn>()` (module-qualified), so each test
monkeypatches the adapter to simulate drift without mutating real repo files."""

from __future__ import annotations


from contracts.sentinel.checks import (
    catalog_consistency,
    catalog_regen,
    pin_consistency,
    schema_columns,
    vector_binary,
    vector_version,
)
from contracts.sentinel.core import sources
from contracts.sentinel.core.drift import Severity


def _ids(findings, severity=None):
    return {f.check_id for f in findings if severity is None or f.severity == severity}


def _blocks(findings):
    return _ids(findings, Severity.BLOCK)


# ── the real repo must be clean (this is what CI enforces) ────────────────────
def test_repo_is_clean():
    findings = []
    for mod in (pin_consistency, catalog_consistency, schema_columns, catalog_regen):
        findings.extend(mod.run())
    assert not _blocks(findings), f"unexpected blocking drift: {_blocks(findings)}"


# ── A0 pin consistency ────────────────────────────────────────────────────────
def test_a0_clean():
    assert not _blocks(pin_consistency.run())


def test_a0_mismatch_blocks(monkeypatch):
    monkeypatch.setattr(
        sources,
        "load_pins",
        lambda: {
            "Makefile:VECTOR_VERSION": "0.56.0",
            "gen-catalog.ts:default": "0.55.0",  # drifted
            "schema/*.json": ["0.56.0"],
            "docker-compose leader (runtime, exempt)": ["0.56.0"],
        },
    )
    assert "A0.pin_mismatch" in _blocks(pin_consistency.run())


def test_a0_empty_schema_set_blocks(monkeypatch):
    # No schema file found at all — must not pass silently (empty any() is False).
    monkeypatch.setattr(
        sources,
        "load_pins",
        lambda: {
            "Makefile:VECTOR_VERSION": "0.56.0",
            "gen-catalog.ts:default": "0.56.0",
            "schema/*.json": [],  # nothing found
            "docker-compose leader (runtime, exempt)": ["0.56.0"],
        },
    )
    assert "A0.pin_mismatch" in _blocks(pin_consistency.run())


def test_a0_leader_lag_is_info_not_block(monkeypatch):
    monkeypatch.setattr(
        sources,
        "load_pins",
        lambda: {
            "Makefile:VECTOR_VERSION": "0.56.0",
            "gen-catalog.ts:default": "0.56.0",
            "schema/*.json": ["0.56.0"],
            "docker-compose leader (runtime, exempt)": ["0.55.0"],  # lags, allowed
        },
    )
    findings = pin_consistency.run()
    assert not _blocks(findings)
    assert "A0.leader_lag" in _ids(findings, Severity.INFO)


# ── C1 backend accepted types ⟷ catalog (strict, kind-aware) ──────────────────
def test_c1_clean_when_equal(monkeypatch):
    same = {"sources": {"file", "amqp"}, "sinks": {"http", "loki"}}
    monkeypatch.setattr(sources, "catalog_kinds", lambda *a, **k: same)
    monkeypatch.setattr(
        sources, "load_backend_types", lambda: {k: set(v) for k, v in same.items()}
    )
    assert not _blocks(catalog_consistency.run())


def test_c1_picker_only_blocks(monkeypatch):
    # Catalog offers a sink the backend doesn't accept → user-reachable 422.
    monkeypatch.setattr(
        sources,
        "catalog_kinds",
        lambda *a, **k: {"sources": {"file"}, "sinks": {"http", "loki"}},
    )
    monkeypatch.setattr(
        sources, "load_backend_types", lambda: {"sources": {"file"}, "sinks": {"http"}}
    )
    findings = catalog_consistency.run()
    assert "C1.sinks_mismatch" in _blocks(findings)
    assert "loki" in findings[0].delta["added"]


def test_c1_backend_only_blocks(monkeypatch):
    # Backend accepts a source the picker never offers.
    monkeypatch.setattr(
        sources,
        "catalog_kinds",
        lambda *a, **k: {"sources": {"file"}, "sinks": {"http"}},
    )
    monkeypatch.setattr(
        sources,
        "load_backend_types",
        lambda: {"sources": {"file", "ghost"}, "sinks": {"http"}},
    )
    findings = catalog_consistency.run()
    assert "C1.sources_mismatch" in _blocks(findings)
    assert "ghost" in findings[0].delta["removed"]


def test_c1_kind_aware(monkeypatch):
    # Same type, wrong kind: 'kafka' offered as a sink but backend only accepts it
    # as a source → both kinds mismatch.
    monkeypatch.setattr(
        sources, "catalog_kinds", lambda *a, **k: {"sources": set(), "sinks": {"kafka"}}
    )
    monkeypatch.setattr(
        sources, "load_backend_types", lambda: {"sources": {"kafka"}, "sinks": set()}
    )
    blocks = _blocks(catalog_consistency.run())
    assert "C1.sinks_mismatch" in blocks and "C1.sources_mismatch" in blocks


# ── C2 model columns ⟷ baseline + ALTERs ──────────────────────────────────────
def _c2_setup(monkeypatch, *, current, baseline, alters):
    monkeypatch.setattr(
        sources, "load_catalog_manifest", lambda: {"schema_version": "x"}
    )
    monkeypatch.setattr(sources, "load_baseline", lambda v: baseline)
    monkeypatch.setattr(sources, "load_model_columns", lambda: current)
    monkeypatch.setattr(sources, "load_upgrade_alters", lambda: alters)


def test_c2_new_column_without_alter_blocks(monkeypatch):
    _c2_setup(
        monkeypatch,
        current={"users": {"id", "email", "new_col"}},  # new_col added
        baseline={"users": ["id", "email"]},
        alters=set(),  # no ALTER for it
    )
    findings = schema_columns.run()
    assert "C2.missing_alter" in _blocks(findings)
    assert "users.new_col" in findings[0].delta["added"]


def test_c2_new_column_with_alter_is_clean(monkeypatch):
    _c2_setup(
        monkeypatch,
        current={"users": {"id", "email", "new_col"}},
        baseline={"users": ["id", "email"]},
        alters={("users", "new_col")},  # ALTER present
    )
    assert not _blocks(schema_columns.run())


def test_c2_new_table_is_not_blocked(monkeypatch):
    _c2_setup(
        monkeypatch,
        current={"users": {"id"}, "brand_new": {"id", "x"}},
        baseline={"users": ["id"]},  # brand_new table absent from baseline
        alters=set(),
    )
    findings = schema_columns.run()
    assert not _blocks(findings)
    assert "C2.new_table" in _ids(findings, Severity.INFO)


def test_c2_missing_baseline_blocks(monkeypatch):
    monkeypatch.setattr(
        sources, "load_catalog_manifest", lambda: {"schema_version": "x"}
    )
    monkeypatch.setattr(sources, "load_baseline", lambda v: None)
    assert "C2.no_baseline" in _blocks(schema_columns.run())


# ── A1 catalog regen freshness ────────────────────────────────────────────────
def test_a1_clean():
    assert not _blocks(catalog_regen.run())


def test_a1_changed_input_blocks(monkeypatch):
    monkeypatch.setattr(
        sources,
        "load_catalog_manifest",
        lambda: {"inputs": {"src/lib/catalog.ts": "deadbeef"}},  # wrong hash
    )
    monkeypatch.setattr(sources, "sha256_file", lambda p: "actualhash")
    assert "A1.catalog_stale" in _blocks(catalog_regen.run())


def test_a1_missing_input_blocks(monkeypatch):
    monkeypatch.setattr(
        sources,
        "load_catalog_manifest",
        lambda: {"inputs": {"src/lib/gone.ts": "abc"}},
    )
    monkeypatch.setattr(sources, "sha256_file", lambda p: None)  # file missing
    assert "A1.input_missing" in _blocks(catalog_regen.run())


# ── A2 schema ⟷ real binary (docker-gated) ────────────────────────────────────
def _a2_setup(monkeypatch, *, docker, committed, live):
    monkeypatch.setattr(sources, "pinned_version", lambda: "0.56.0")
    monkeypatch.setattr(sources, "load_committed_schema", lambda v: committed)
    monkeypatch.setattr(sources, "docker_available", lambda: docker)
    monkeypatch.setattr(sources, "fetch_vector_schema_via_docker", lambda v: live)


def test_a2_skips_without_docker(monkeypatch):
    _a2_setup(monkeypatch, docker=False, committed=b"{}", live=None)
    findings = vector_binary.run()
    assert not _blocks(findings)
    assert "A2.skipped" in _ids(findings, Severity.INFO)


def test_a2_match_is_clean(monkeypatch):
    # Same content, different whitespace/key order → still equal (normalized).
    _a2_setup(
        monkeypatch, docker=True, committed=b'{"a":1,"b":2}', live=b'{"b":2, "a":1}'
    )
    assert vector_binary.run() == []


def test_a2_stale_blocks(monkeypatch):
    _a2_setup(monkeypatch, docker=True, committed=b'{"a":1}', live=b'{"a":2}')
    assert "A2.schema_stale" in _blocks(vector_binary.run())


def test_a2_missing_committed_blocks(monkeypatch):
    _a2_setup(monkeypatch, docker=True, committed=None, live=b"{}")
    assert "A2.no_committed_schema" in _blocks(vector_binary.run())


# ── A3 newer version available (network-gated, info only) ─────────────────────
def test_a3_update_available_is_info(monkeypatch):
    monkeypatch.setattr(sources, "pinned_version", lambda: "0.56.0")
    monkeypatch.setattr(
        sources, "fetch_latest_vector_release", lambda *a, **k: "0.99.0"
    )
    findings = vector_version.run()
    assert not _blocks(findings)
    assert "A3.update_available" in _ids(findings, Severity.INFO)


def test_a3_not_newer_is_clean(monkeypatch):
    monkeypatch.setattr(sources, "pinned_version", lambda: "0.56.0")
    monkeypatch.setattr(
        sources, "fetch_latest_vector_release", lambda *a, **k: "0.56.0"
    )
    assert vector_version.run() == []


def test_a3_offline_skips(monkeypatch):
    monkeypatch.setattr(sources, "pinned_version", lambda: "0.56.0")
    monkeypatch.setattr(sources, "fetch_latest_vector_release", lambda *a, **k: None)
    assert "A3.skipped" in _ids(vector_version.run(), Severity.INFO)


def test_version_tuple_compares():
    assert sources.version_tuple("0.57.0") > sources.version_tuple("0.56.0")
    assert sources.version_tuple("0.56.1") > sources.version_tuple("0.56.0")


# ── CLI: a crashing check degrades to one BLOCK, never masks the others ────────
def test_check_crash_degrades_to_block(monkeypatch):
    from contracts.sentinel import cli

    def boom():
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(cli.pin_consistency, "run", boom)
    # Other checks still run; the crash becomes a BLOCK so the run exits 1.
    assert cli._check() == 1
