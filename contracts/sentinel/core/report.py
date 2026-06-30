# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Render findings for the terminal / CI log."""

from __future__ import annotations

from .drift import Finding, Severity

_ORDER = [Severity.BLOCK, Severity.ADVISORY, Severity.INFO]
_LABEL = {Severity.BLOCK: "BLOCK", Severity.ADVISORY: "ADVISORY", Severity.INFO: "INFO"}
_MAX_ITEMS = 12  # truncate long deltas so the log stays readable


def _fmt_delta(delta: dict[str, list]) -> list[str]:
    lines: list[str] = []
    for kind in ("added", "removed", "changed"):
        items = delta.get(kind) or []
        if not items:
            continue
        shown = ", ".join(str(x) for x in items[:_MAX_ITEMS])
        more = (
            f" … (+{len(items) - _MAX_ITEMS} more)" if len(items) > _MAX_ITEMS else ""
        )
        lines.append(f"      {kind}: {shown}{more}")
    return lines


def render(findings: list[Finding]) -> tuple[str, bool]:
    """Return (text, has_block)."""
    by_sev: dict[Severity, list[Finding]] = {s: [] for s in _ORDER}
    for f in findings:
        by_sev[f.severity].append(f)

    out: list[str] = []
    counts = " · ".join(f"{len(by_sev[s])} {_LABEL[s].lower()}" for s in _ORDER)
    out.append(f"Contract Drift Sentinel — {counts}")
    out.append("=" * 60)

    for sev in _ORDER:
        for f in by_sev[sev]:
            out.append(f"[{_LABEL[sev]}] {f.check_id}: {f.summary}")
            out.extend(_fmt_delta(f.delta))
            if f.remediation:
                out.append(f"      → {f.remediation}")
            out.append("")

    has_block = bool(by_sev[Severity.BLOCK])
    if not findings:
        out.append("No drift detected. ✓")
    elif not has_block:
        out.append("No blocking drift. ✓ (advisory/info only)")
    else:
        out.append(f"FAIL — {len(by_sev[Severity.BLOCK])} blocking finding(s).")
    return "\n".join(out), has_block
