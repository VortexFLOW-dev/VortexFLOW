# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contract Drift Sentinel CLI.

    python -m contracts.sentinel check            # offline checks; exit 1 on any BLOCK
    python -m contracts.sentinel check --online   # + docker/network A2/A3 (P2)
    python -m contracts.sentinel baseline         # snapshot model columns for C2

Run from the repo root with the backend importable,
e.g. `make sentinel`."""

from __future__ import annotations

import argparse
import os
import secrets

# Importing the backend app validates settings at import (a secret key is
# required). Use a throwaway if the caller didn't set one — never persisted,
# only used to let model/schema modules import. Mirrors the CI test job.
os.environ.setdefault("VORTEXFLOW_SECRET_KEY", secrets.token_hex(32))

from .checks import (  # noqa: E402
    catalog_consistency,
    catalog_regen,
    pin_consistency,
    schema_columns,
    vector_binary,
    vector_version,
)
from .core import report, sources  # noqa: E402
from .core.drift import Finding, block  # noqa: E402

# Offline P1 checks (no docker/node/DB), in display order.
OFFLINE_CHECKS = [pin_consistency, catalog_consistency, schema_columns, catalog_regen]
# P2 checks needing docker/network; skip gracefully when unavailable.
ONLINE_CHECKS = [vector_binary, vector_version]


def _run(mods) -> list[Finding]:
    findings: list[Finding] = []
    for mod in mods:
        # A crashing check degrades to one BLOCK finding rather than aborting the
        # whole run and masking the other checks' results.
        try:
            findings.extend(mod.run())
        except Exception as e:  # noqa: BLE001 — surface, don't propagate
            findings.append(
                block(
                    f"{mod.__name__.rsplit('.', 1)[-1]}.crashed",
                    f"check raised {type(e).__name__}: {e}",
                    remediation="fix the check or the artifact it reads",
                )
            )
    return findings


def _check(online: bool = False) -> int:
    mods = OFFLINE_CHECKS + (ONLINE_CHECKS if online else [])
    text, has_block = report.render(_run(mods))
    print(text)
    return 1 if has_block else 0


def _baseline() -> int:
    manifest = sources.load_catalog_manifest()
    version = manifest.get("schema_version", "unknown")
    columns = sources.load_model_columns()
    path = sources.write_baseline(version, columns)
    total = sum(len(c) for c in columns.values())
    print(
        f"Wrote baseline for {len(columns)} table(s) / {total} column(s) to "
        f"{path.relative_to(sources.REPO_ROOT)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contracts.sentinel")
    sub = parser.add_subparsers(dest="cmd")
    check_p = sub.add_parser("check", help="run drift checks (exit 1 on any BLOCK)")
    check_p.add_argument(
        "--online",
        action="store_true",
        help="also run docker/network checks (A2 schema, A3 version); skip gracefully if unavailable",
    )
    sub.add_parser("baseline", help="snapshot model columns for the C2 check")
    args = parser.parse_args(argv)

    if args.cmd == "baseline":
        return _baseline()
    return _check(online=getattr(args, "online", False))
