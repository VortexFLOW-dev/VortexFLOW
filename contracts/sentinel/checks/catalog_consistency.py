# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""C1 — backend accepted types ⟷ catalog (the picker), kind-aware.

Both lists are generated from the same Vector schema by one codegen step
(`make catalog`), so they MUST be equal per kind. A difference means someone
regenerated/edited one side but not the other (e.g. forgot to commit the backend
`catalog_types.json`). Either direction is a real bug:

    catalog − backend : a type the picker offers but the backend 422s
    backend − catalog : a type the backend accepts but the picker never offers
"""

from __future__ import annotations

from ..core import sources
from ..core.drift import Finding, block


def run() -> list[Finding]:
    catalog = sources.catalog_kinds()  # frontend picker
    backend = sources.load_backend_types()  # backend acceptance gate
    findings: list[Finding] = []

    for kind in ("sources", "sinks"):
        offered = catalog.get(kind, set())
        accepted = backend.get(kind, set())
        picker_only = sorted(offered - accepted)  # user-selectable but 422
        backend_only = sorted(accepted - offered)  # accepted but unreachable
        if picker_only or backend_only:
            delta: dict[str, list] = {}
            if picker_only:
                delta["added"] = picker_only
            if backend_only:
                delta["removed"] = backend_only
            findings.append(
                block(
                    f"C1.{kind}_mismatch",
                    f"backend accepted {kind} disagree with the catalog "
                    f"({len(picker_only)} picker-only, {len(backend_only)} backend-only)",
                    delta=delta,
                    remediation=(
                        "regenerate both with `make catalog` (or `pnpm gen:catalog`) "
                        "and commit backend/app/data/catalog_types.json"
                    ),
                )
            )

    return findings
