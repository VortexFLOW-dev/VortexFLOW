# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Server-side VRL validate/run via the bundled `vector vrl` binary.

Unlike the GraphQL `testRemap` path (which needs a reachable Vector *instance*),
this runs the VRL program against a sample event using the bundled binary directly
— so it works with **zero instances online**. That makes it the instant
compile-checker for the editor, and the foundation for the (post-launch) AI VRL
assistant's generate→validate→repair loop.

Safe by construction: program + event are written to temp files and passed as an
arg list (no shell), the subprocess is time-bounded, and VRL itself is a pure
transformation DSL (no filesystem/network access from a program).

Degrades gracefully: if the binary isn't bundled (e.g. a dev box), returns
`source="unavailable"` rather than raising — callers fall back to instance testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_MAX_ERR = 4000
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Vector logs to stderr (e.g. `2026-… INFO vector::app: Log level is enabled`).
# Drop those so the user sees only their program's output / VRL diagnostic.
_LOG_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+(?:INFO|WARN|WARNING|ERROR|DEBUG|TRACE)\b"
)


@dataclass
class VrlRunResult:
    ok: bool
    output: dict | None = None
    error: str | None = None
    source: str = "vector-cli"  # "vector-cli" | "unavailable"


def _strip_logs(s: str) -> str:
    """Drop Vector's own stderr log lines, leaving program output / diagnostics."""
    return "\n".join(ln for ln in s.splitlines() if not _LOG_LINE.match(ln.strip()))


def _clean(s: str) -> str:
    """Strip ANSI codes + Vector log lines from a diagnostic; cap the length."""
    return _strip_logs(_ANSI.sub("", s)).strip()[:_MAX_ERR]


async def run_vrl(program: str, event: dict) -> VrlRunResult:
    """Run `program` against `event` with the bundled Vector and return the result.

    `vector vrl --input <event> --program <prog> --print-object` prints the modified
    event as JSON on success; a compile/runtime error exits non-zero with a
    human-readable diagnostic on stderr.
    """
    tmpdir = tempfile.mkdtemp(prefix="vrl_")
    prog_path = os.path.join(tmpdir, "program.vrl")
    event_path = os.path.join(tmpdir, "event.json")
    try:
        with open(prog_path, "w", encoding="utf-8") as f:
            f.write(program)
        with open(event_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(event))

        try:
            proc = await asyncio.create_subprocess_exec(
                settings.vector_bin,
                "vrl",
                "--input",
                event_path,
                "--program",
                prog_path,
                "--print-object",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return VrlRunResult(
                ok=False,
                source="unavailable",
                error="Server-side VRL validation is unavailable on this deployment "
                "(the Vector binary is not bundled). Run against an instance instead.",
            )

        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return VrlRunResult(ok=False, error="VRL evaluation timed out.")

        if proc.returncode != 0:
            msg = err.decode("utf-8", "replace") or out.decode("utf-8", "replace")
            return VrlRunResult(ok=False, error=_clean(msg) or "VRL evaluation failed.")

        # stdout is the modified event (one JSON object); Vector's logs go to
        # stderr, but strip defensively in case logging is reconfigured.
        text = _strip_logs(_ANSI.sub("", out.decode("utf-8", "replace"))).strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            first = text.splitlines()[0] if text else ""
            try:
                obj = json.loads(first)
            except json.JSONDecodeError:
                return VrlRunResult(ok=True, output={"_output": text})
        return VrlRunResult(
            ok=True, output=obj if isinstance(obj, dict) else {"_value": obj}
        )
    finally:
        for p in (prog_path, event_path):
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
