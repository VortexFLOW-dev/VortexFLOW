# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Agent control-plane endpoints (pull-based config sync).

These are authenticated by a long-lived per-agent token (minted at registration,
bcrypt-hashed into `instance.agent_token_hash`), NOT by a user JWT. The agent
identifies itself by instance id in the path so the token is verified against a
single instance's hash rather than scanned across the fleet.

Contract:
  GET  /agent/{instance_id}/config  -> rendered fleet config + globals + generation
  POST /agent/{instance_id}/status  -> agent reports applied generation + health
"""

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.settings import _get_setting
from app.core.config import settings
from app.core.database import get_db
from app.core.security import dummy_verify, verify_password
from app.models.instance import Instance
from app.models.fleet import Fleet
from app.services import config_render, deployed_config

log = logging.getLogger("vortexflow.agent")
router = APIRouter()


class AgentStatusBody(BaseModel):
    applied_generation: int
    vector_healthy: bool
    status: str = "ok"
    last_error: str | None = None
    vector_version: str | None = None


class AgentFile(BaseModel):
    """A file the agent must write on the host before validate+reload — TLS cert
    material referenced by the config. ``mode`` is a POSIX permission int."""

    path: str
    content: str
    mode: int = 0o644


class AgentConfigResponse(BaseModel):
    generation: int
    config_yaml: str
    warnings: list[str]
    # Fleet-wide desired Vector version ("" = unmanaged). The agent reconciles
    # its host to this before applying the config.
    vector_version: str = ""
    # Extra files (TLS certs/keys) to write before applying the config. The
    # config's tls.*_file paths point at these. Written 0600 for keys.
    files: list[AgentFile] = []


async def _authenticate_agent(
    instance_id: str,
    authorization: str | None,
    db: AsyncSession,
) -> Instance:
    """Verify the Bearer token against the named instance's stored hash.

    Returns the instance on success; raises 401 otherwise. Errors are
    intentionally generic so a caller can't distinguish 'no such instance' from
    'wrong token'.
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing agent token"
        )

    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    token_hash = (
        instance.agent_token_hash
        if instance is not None and instance.is_active and instance.agent_token_hash
        else None
    )
    # Always burn exactly one bcrypt cycle: verify the real hash when there is
    # one, else a dummy — so an unknown/inactive instance can't be distinguished
    # from a wrong token by response timing (instance-id enumeration).
    if token_hash is not None:
        ok = verify_password(token, token_hash)
    else:
        dummy_verify()
        ok = False
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token"
        )
    assert instance is not None  # ok is True only when a real hash was verified
    return instance


@router.get("/{instance_id}/config", response_model=None)
async def agent_config(
    instance_id: str,
    response: Response,
    authorization: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigResponse | Response:
    """Return the rendered Vector config for this agent's fleet, with the
    instance's globals merged in. The ETag is content-addressed, so a 304 is
    returned whenever the effective config (topology *or* this host's globals)
    is unchanged — the agent reloads only on a real change."""
    instance = await _authenticate_agent(instance_id, authorization, db)

    if not instance.fleet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance is not assigned to a fleet",
        )

    fleet_result = await db.execute(select(Fleet).where(Fleet.id == instance.fleet_id))
    fleet = fleet_result.scalar_one_or_none()
    if fleet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found"
        )

    # Serve ONLY the last successfully-deployed snapshot — never a live DB render.
    # This is what makes Deploy the publish gate: an editor's un-deployed edit
    # cannot reach a host, and an agent never receives config that hasn't passed
    # `vector validate`. A fleet that has never deployed successfully returns 304,
    # so the agent keeps its last-good config until an operator deploys.
    if not fleet.deployed_config:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    try:
        snapshot = deployed_config.decode(fleet.deployed_config, settings.at_rest_key)
    except Exception:
        # Snapshot won't decrypt/parse — e.g. VORTEXFLOW_SECRET_KEY was rotated
        # after this fleet's last deploy. Degrade gracefully: keep the agent on
        # its last-good config (304) rather than 500. A fresh deploy re-encrypts
        # the snapshot under the current key.
        log.warning(
            "agent %s: deployed_config for fleet %s failed to decrypt; serving 304",
            instance_id,
            fleet.id,
        )
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    snap_config = snapshot["config"]
    snap_files = snapshot["files"]
    snap_warnings = snapshot["warnings"]

    content = config_render.serialize_with_globals(
        snap_config,
        data_dir=instance.data_dir,
        expire_metrics_secs=instance.expire_metrics_secs,
    )

    # Desired Vector version: this fleet's override wins, else the global default
    # (general settings). Lets a version roll to one fleet at a time.
    from app.services.fleet_view import effective_vector_version

    general = await _get_setting("general", db)
    desired_version = effective_vector_version(
        fleet, str(general.get("desired_vector_version", "") or "")
    )

    # ETag covers config content, desired version, AND the cert files — changing
    # any of them invalidates the agent's cache and triggers reconciliation, so a
    # rotated cert reaches the host even when the config text is unchanged.
    files_fingerprint = hashlib.sha256(
        "\x00".join(
            f"{f['path']}:{f['content']}"
            for f in sorted(snap_files, key=lambda x: x["path"])
        ).encode()
    ).hexdigest()
    etag = (
        '"'
        + hashlib.sha256(
            (content + "\x00" + desired_version + "\x00" + files_fingerprint).encode()
        ).hexdigest()[:32]
        + '"'
    )
    if if_none_match is not None and if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    response.headers["ETag"] = etag
    return AgentConfigResponse(
        generation=fleet.generation,
        config_yaml=content,
        warnings=snap_warnings,
        vector_version=desired_version,
        files=[AgentFile(**f) for f in snap_files],
    )


@router.post("/{instance_id}/status")
async def agent_status(
    instance_id: str,
    body: AgentStatusBody,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record the agent's reported state — applied generation, health, last seen.
    Drives the Fleets/Health rollout view."""
    instance = await _authenticate_agent(instance_id, authorization, db)

    instance.applied_generation = body.applied_generation
    instance.agent_status = body.status
    instance.agent_last_seen = datetime.now(timezone.utc)
    if body.vector_version:
        instance.vector_version = body.vector_version
    db.add(instance)
    await db.commit()
    return {"ok": True}
