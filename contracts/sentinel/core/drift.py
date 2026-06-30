# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The Finding model — every check emits structured Findings, never booleans.

A Finding carries the *exact delta* that drifted (so the output is the backlog)
and a severity that maps onto a surface:

    block     -> red CI check (PR gate)
    advisory  -> pre-push hook line (never blocks)
    info      -> /daily-status line
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    BLOCK = "block"
    ADVISORY = "advisory"
    INFO = "info"


@dataclass
class Finding:
    check_id: str
    severity: Severity
    summary: str
    # Structured delta — any of added/removed/changed; keep lists JSON-friendly.
    delta: dict[str, list] = field(default_factory=dict)
    remediation: str = ""


def block(check_id: str, summary: str, **kw) -> Finding:
    return Finding(check_id, Severity.BLOCK, summary, **kw)


def advisory(check_id: str, summary: str, **kw) -> Finding:
    return Finding(check_id, Severity.ADVISORY, summary, **kw)


def info(check_id: str, summary: str, **kw) -> Finding:
    return Finding(check_id, Severity.INFO, summary, **kw)
