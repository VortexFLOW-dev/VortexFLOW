# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A2 — committed schema ⟷ real Vector binary (docker-gated, P2).

Re-runs `docker run timberio/vector:<pin>-alpine generate-schema` (exactly what
`make catalog` does) and compares to the committed `schema/vector-<pin>.json`.
Catches a stale or hand-edited schema snapshot. Skips gracefully (INFO) when
docker is unavailable, so this can live in the same runner as the offline checks
without breaking local/offline runs."""

from __future__ import annotations

import json

from ..core import sources
from ..core.drift import Finding, block, info


def _normalize(raw: bytes) -> object:
    # Compare structurally (key order / whitespace independent).
    return json.loads(raw)


def run() -> list[Finding]:
    version = sources.pinned_version()
    if not version:
        return [
            block(
                "A2.no_pin",
                "could not determine the pinned Vector version",
                remediation="ensure Makefile defines VECTOR_VERSION",
            )
        ]

    committed = sources.load_committed_schema(version)
    if committed is None:
        return [
            block(
                "A2.no_committed_schema",
                f"committed schema/vector-{version}-schema.json is missing",
                remediation="`make catalog` to fetch and commit it",
            )
        ]

    if not sources.docker_available():
        return [
            info(
                "A2.skipped",
                "docker unavailable — skipped real-binary schema check (offline)",
            )
        ]

    live = sources.fetch_vector_schema_via_docker(version)
    if live is None:
        return [
            info(
                "A2.skipped",
                f"could not run `vector:{version} generate-schema` — skipped",
            )
        ]

    if _normalize(live) != _normalize(committed):
        return [
            block(
                "A2.schema_stale",
                f"committed schema differs from what vector:{version} emits — the "
                "snapshot is stale or hand-edited",
                remediation="`make catalog` (re-fetch the schema) and commit the result",
            )
        ]
    return []
