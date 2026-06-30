# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""C2 — model columns ⟷ baseline + ALTERs.

A column added to a model since the last release MUST also be added by an
`ALTER TABLE ... ADD COLUMN` in `_run_schema_upgrades()`, or existing DBs won't
get it on upgrade (create_all only touches fresh DBs) → deploy crash.

    needs_alter = current model columns − baseline (columns added since release)
    missing     = needs_alter not covered by an ALTER   → BLOCK

New *tables* are skipped (create_all builds missing tables on existing DBs too)."""

from __future__ import annotations

from ..core import sources
from ..core.drift import Finding, block, info


def run() -> list[Finding]:
    manifest = sources.load_catalog_manifest()
    version = manifest.get("schema_version", "unknown")

    baseline = sources.load_baseline(version)
    if baseline is None:
        return [
            block(
                "C2.no_baseline",
                f"no column baseline for the pinned version (contracts/baseline/"
                f"columns-{version}.json missing)",
                remediation="`make sentinel-baseline` to seed it from current models",
            )
        ]

    current = sources.load_model_columns()
    alters = sources.load_upgrade_alters()  # {(table, column)}
    findings: list[Finding] = []

    missing: list[str] = []
    for table, base_cols in baseline.items():
        if table not in current:
            continue  # dropped table — not C2's concern
        new_cols = current[table] - set(base_cols)
        for col in sorted(new_cols):
            if (table, col) not in alters:
                missing.append(f"{table}.{col}")

    if missing:
        findings.append(
            block(
                "C2.missing_alter",
                f"{len(missing)} model column(s) added since {version} have no "
                "ALTER in _run_schema_upgrades() — existing DBs won't get them on upgrade",
                delta={"added": missing},
                remediation=(
                    "add `ALTER TABLE <t> ADD COLUMN IF NOT EXISTS <c> ...` to "
                    "_run_schema_upgrades() in backend/app/main.py"
                ),
            )
        )

    # New tables: fine (create_all covers them) but worth a nudge to refresh.
    new_tables = sorted(set(current) - set(baseline))
    if new_tables:
        findings.append(
            info(
                "C2.new_table",
                f"{len(new_tables)} table(s) are new since the baseline "
                "(create_all covers these on existing DBs)",
                delta={"added": new_tables},
                remediation="`make sentinel-baseline` at next release to refresh the floor",
            )
        )

    # Dead ALTERs: an ADD COLUMN for a column no model declares anymore.
    model_pairs = {(t, c) for t, cols in current.items() for c in cols}
    dead = sorted(f"{t}.{c}" for (t, c) in alters if (t, c) not in model_pairs)
    if dead:
        findings.append(
            info(
                "C2.dead_alter",
                f"{len(dead)} ALTER ADD COLUMN(s) reference a column no model declares",
                delta={"removed": dead},
            )
        )

    return findings
