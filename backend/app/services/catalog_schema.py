# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Live Vector schema for the source/sink catalog.

Runs the bundled `vector generate-schema` (the image bakes the binary at
VORTEXFLOW_VECTOR_BIN) and caches the result in-process — the bundled binary's
version is fixed per image, so the schema is effectively constant until a refresh
or restart. The frontend converts this schema into catalog forms at runtime, so
the catalog tracks the deployed Vector without a frontend rebuild.

Degrades gracefully: if the binary isn't present (e.g. a dev box), callers get
None and fall back to the catalog bundled in the frontend.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30
# Cached raw schema JSON (bytes) + parsed Vector version string.
_cache: dict[str, object] = {"raw": None, "version": None}


async def _run_vector(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        settings.vector_bin,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("vector timed out")
    if proc.returncode != 0:
        raise RuntimeError(err.decode("utf-8", "replace")[:500])
    return out


async def get_vector_version() -> str | None:
    """Return the bundled Vector semver (e.g. '0.56.0'), or None if unavailable."""
    if _cache["version"]:
        return str(_cache["version"])
    try:
        out = (await _run_vector("--version")).decode("utf-8", "replace")
    except (FileNotFoundError, RuntimeError) as e:
        logger.info("vector --version unavailable: %s", e)
        return None
    parts = out.split()
    version = parts[1] if len(parts) > 1 else out.strip()
    _cache["version"] = version
    return version


async def get_schema_json(force: bool = False) -> bytes | None:
    """Return the raw `vector generate-schema` JSON (bytes), cached. None if the
    Vector binary isn't available."""
    if _cache["raw"] is not None and not force:
        return _cache["raw"]  # type: ignore[return-value]
    try:
        raw = await _run_vector("generate-schema")
    except FileNotFoundError:
        return None  # binary not bundled (dev / non-image runtime)
    except RuntimeError as e:
        logger.warning("vector generate-schema failed: %s", e)
        return None
    _cache["raw"] = raw
    # Refresh the version alongside the schema.
    _cache["version"] = None
    await get_vector_version()
    return raw


def clear_cache() -> None:
    _cache["raw"] = None
    _cache["version"] = None
