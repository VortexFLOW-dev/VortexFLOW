# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A3 — newer Vector release available (network-gated, P2; info only).

Compares the latest upstream Vector release to the pinned version. INFO only —
a bump is a deliberate, reviewed event (bump VECTOR_VERSION → `make catalog` →
A0/A1/A2 become the migration checklist). Surfaces in /daily-status. Skips
gracefully when offline."""

from __future__ import annotations

from ..core import sources
from ..core.drift import Finding, info


def run() -> list[Finding]:
    version = sources.pinned_version()
    if not version:
        return []  # A2 already blocks on a missing pin; don't double-report.

    latest = sources.fetch_latest_vector_release()
    if latest is None:
        return [info("A3.skipped", "offline — skipped Vector release check")]

    if sources.version_tuple(latest) > sources.version_tuple(version):
        return [
            info(
                "A3.update_available",
                f"Vector {latest} is available; pinned at {version}",
                delta={"changed": [f"{version} → {latest}"]},
                remediation=(
                    "when ready: bump VECTOR_VERSION, `make catalog`, then let "
                    "A0/A1/A2 + the catalog/column diffs guide the upgrade"
                ),
            )
        ]
    return []
