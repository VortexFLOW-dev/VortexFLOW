# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A1 — catalog regeneration freshness (offline, no node).

The committed catalog manifest records a sha256 of every input the catalog is
derived from (schema JSON, converter, catalog.ts, generated.ts). Recompute them
in pure Python: any mismatch means an input changed but the catalog wasn't
regenerated."""

from __future__ import annotations

from ..core import sources
from ..core.drift import Finding, block


def run() -> list[Finding]:
    manifest = sources.load_catalog_manifest()
    inputs: dict[str, str] = manifest.get("inputs", {})
    if not inputs:
        return [
            block(
                "A1.no_input_hashes",
                "catalog.manifest.json has no input hashes",
                remediation="regenerate with `make catalog` (or `pnpm gen:catalog`)",
            )
        ]

    stale: list[str] = []
    missing: list[str] = []
    for rel, expected in inputs.items():
        actual = sources.sha256_file(sources.FRONTEND / rel)
        if actual is None:
            missing.append(rel)
        elif actual != expected:
            stale.append(rel)

    findings: list[Finding] = []
    if missing:
        findings.append(
            block(
                "A1.input_missing",
                f"{len(missing)} catalog input file(s) recorded in the manifest are gone",
                delta={"removed": missing},
                remediation="restore the file(s) or regenerate with `make catalog`",
            )
        )
    if stale:
        findings.append(
            block(
                "A1.catalog_stale",
                f"{len(stale)} catalog input(s) changed since the catalog was generated "
                "— the committed catalog/manifest is out of date",
                delta={"changed": stale},
                remediation="`make catalog` (or `pnpm gen:catalog`) and commit the result",
            )
        )
    return findings
