# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A0 — pin consistency.

Assert one Vector version across every pin. The docker-compose leader is a
*runtime* version (allowed to differ) — only flagged INFO if it lags."""

from __future__ import annotations

from ..core import sources
from ..core.drift import Finding, block, info

# Makefile is canonical (the comment there says "bump here, then make catalog").
CANONICAL = "Makefile:VECTOR_VERSION"
LEADER_KEY = "docker-compose leader (runtime, exempt)"


def run() -> list[Finding]:
    pins = sources.load_pins()
    findings: list[Finding] = []

    canonical = pins.get(CANONICAL)
    if not canonical:
        return [
            block(
                "A0.pin_unreadable",
                f"could not read the canonical pin ({CANONICAL})",
                remediation="confirm `VECTOR_VERSION ?= x.y.z` exists in the Makefile",
            )
        ]

    # Build-time pins that MUST equal the canonical one.
    mismatched: dict[str, list] = {}
    for key, val in pins.items():
        if key in (CANONICAL, LEADER_KEY):
            continue
        # schema/*.json is a list — every committed schema must match the pin.
        actual = val if isinstance(val, list) else [val]
        # An empty list (e.g. no schema file found) is itself drift — an empty
        # `any()` is False, so flag it explicitly rather than passing silently.
        if not actual or any(v != canonical for v in actual):
            mismatched[key] = actual

    if mismatched:
        findings.append(
            block(
                "A0.pin_mismatch",
                f"Vector version pins disagree with {CANONICAL}={canonical!r}",
                delta={"changed": [f"{k} = {v}" for k, v in mismatched.items()]},
                remediation=(
                    "align every pin to the canonical Makefile version, then "
                    "`make catalog` to regenerate"
                ),
            )
        )

    leader = pins.get(LEADER_KEY) or []
    lagging = [v for v in leader if v != canonical]
    if lagging:
        findings.append(
            info(
                "A0.leader_lag",
                f"docker-compose leader Vector ({', '.join(lagging)}) lags the pin "
                f"({canonical}) — runtime version, intentional unless you forgot to bump",
                delta={"changed": lagging},
            )
        )

    return findings
