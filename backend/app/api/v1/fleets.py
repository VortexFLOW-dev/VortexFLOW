# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.netutil import client_ip
from app.core.security import get_password_hash
from app.middleware.rbac import require_admin, require_editor, require_viewer
from app.models.component import Component
from app.models.instance import Instance
from app.models.route import Route
from app.models.fleet import Fleet
from app.models.user import User
from app.services import audit, cert_delivery, config_render, deployed_config
from app.schemas.fleet import (
    AddInstanceToFleetRequest,
    InstanceInFleet,
    RegisterAgentRequest,
    RegisterAgentResponse,
    FleetBootstrapResponse,
    FleetCreate,
    FleetListResponse,
    FleetResponse,
    FleetUpdate,
)
from app.services import redis_client

_REGISTER_MAX_FAILURES = 5
_REGISTER_LOCKOUT_TTL = 600  # 10 minutes

router = APIRouter()


@router.get("", response_model=FleetListResponse)
async def list_fleets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> FleetListResponse:
    result = await db.execute(select(Fleet).order_by(Fleet.created_at))
    fleets = result.scalars().all()
    return FleetListResponse(
        fleets=[FleetResponse.model_validate(s) for s in fleets],
        total=len(fleets),
    )


@router.post("", response_model=FleetResponse, status_code=status.HTTP_201_CREATED)
async def create_fleet(
    body: FleetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> FleetResponse:
    fleet = Fleet(
        name=body.name,
        description=body.description,
        created_by=current_user.id,
    )
    db.add(fleet)
    await db.commit()
    await db.refresh(fleet)
    return FleetResponse.model_validate(fleet)


@router.get("/{fleet_id}", response_model=dict)
async def get_fleet(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> dict:
    fleet = await _get_fleet_or_404(fleet_id, db)
    result = await db.execute(
        select(Instance)
        .where(Instance.fleet_id == fleet_id)
        .order_by(Instance.created_at)
    )
    instances = result.scalars().all()
    return {
        **FleetResponse.model_validate(fleet).model_dump(),
        "instances": [
            InstanceInFleet.model_validate(i).model_dump() for i in instances
        ],
    }


@router.patch("/{fleet_id}", response_model=FleetResponse)
async def update_fleet(
    fleet_id: str,
    body: FleetUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> FleetResponse:
    fleet = await _get_fleet_or_404(fleet_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(fleet, field, value)
    db.add(fleet)
    await db.commit()
    await db.refresh(fleet)
    return FleetResponse.model_validate(fleet)


@router.delete("/{fleet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fleet(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    fleet = await _get_fleet_or_404(fleet_id, db)
    if fleet.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the default fleet",
        )
    await db.delete(fleet)
    await db.commit()


@router.get("/{fleet_id}/delete-impact")
async def fleet_delete_impact(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> dict:
    """The blast radius of deleting this fleet — config hard-deleted (cascade) and
    instances detached (set null) — so the UI can show it before a type-DELETE."""
    fleet = await _get_fleet_or_404(fleet_id, db)
    comps = (
        (await db.execute(select(Component).where(Component.fleet_id == fleet_id)))
        .scalars()
        .all()
    )
    routes = (
        (await db.execute(select(Route).where(Route.fleet_id == fleet_id)))
        .scalars()
        .all()
    )
    stages, _vrl = await _load_stages(fleet_id, db)
    instances = (
        (await db.execute(select(Instance).where(Instance.fleet_id == fleet_id)))
        .scalars()
        .all()
    )
    return {
        "is_default": fleet.is_default,
        "sources": sum(1 for c in comps if c.kind == "source"),
        "sinks": sum(1 for c in comps if c.kind == "sink"),
        "routes": len(routes),
        "stages": len(stages),
        "instances": [i.label for i in instances],
    }


@router.post("/{fleet_id}/instances/{instance_id}", response_model=InstanceInFleet)
async def add_instance_to_fleet(
    fleet_id: str,
    instance_id: str,
    body: AddInstanceToFleetRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> InstanceInFleet:
    await _get_fleet_or_404(fleet_id, db)
    instance = await _get_instance_or_404(instance_id, db)

    instance.fleet_id = fleet_id
    instance.role = body.role
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return InstanceInFleet.model_validate(instance)


@router.delete(
    "/{fleet_id}/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_instance_from_fleet(
    fleet_id: str,
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    instance = await _get_instance_or_404(instance_id, db)
    if instance.fleet_id != fleet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance is not a member of this fleet",
        )
    instance.fleet_id = None
    db.add(instance)
    await db.commit()


@router.post("/{fleet_id}/bootstrap-token", response_model=FleetBootstrapResponse)
async def generate_bootstrap_token(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> FleetBootstrapResponse:
    fleet = await _get_fleet_or_404(fleet_id, db)
    plain_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
    fleet.bootstrap_token_hash = token_hash
    db.add(fleet)
    await db.commit()
    return FleetBootstrapResponse(token=plain_token)


@router.post("/{fleet_id}/register", response_model=RegisterAgentResponse)
async def register_agent(
    fleet_id: str,
    body: RegisterAgentRequest,
    request: Request,
    x_bootstrap_token: str = Header(..., alias="X-Bootstrap-Token"),
    db: AsyncSession = Depends(get_db),
) -> RegisterAgentResponse:
    """Self-registration endpoint called by the bootstrap install script.
    Authenticates via the fleet bootstrap token, then creates or updates
    an Instance record for the registering host."""
    # Use the real client IP (honouring trusted proxies) so the per-IP register
    # rate limit isn't keyed on nginx's address — otherwise every agent shares
    # one bucket (both an ineffective throttle and a fleet-wide DoS lever).
    ip = client_ip(request)
    rate_key = f"register:{ip}"

    # Rate limit: block IPs that have repeatedly failed
    failures = await redis_client.get_login_failures(rate_key)
    if failures >= _REGISTER_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts — try again later",
        )

    fleet = await _get_fleet_or_404(fleet_id, db)

    if not fleet.bootstrap_token_hash:
        await redis_client.record_login_failure(rate_key, ttl=_REGISTER_LOCKOUT_TTL)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bootstrap token not configured for this fleet",
        )

    candidate_hash = hashlib.sha256(x_bootstrap_token.encode()).hexdigest()
    if not hmac.compare_digest(candidate_hash, fleet.bootstrap_token_hash):
        await redis_client.record_login_failure(rate_key, ttl=_REGISTER_LOCKOUT_TTL)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bootstrap token",
        )

    # Clear failure counter on success
    await redis_client.clear_login_failures(rate_key)

    # Mint a long-lived per-agent token; only its bcrypt hash is stored. Returned
    # once so the agent can authenticate config polls and status reports.
    # Re-registration rotates the token.
    agent_token = secrets.token_urlsafe(32)
    token_hash = get_password_hash(agent_token)

    # Upsert scoped to THIS fleet only. The lookup is deliberately constrained to
    # fleet_id: a previous version queried api_url across all fleets and 409'd on
    # a cross-fleet match, which let a bootstrap-token holder enumerate which
    # api_urls exist in other fleets (201-vs-409 oracle). A caller only ever sees
    # its own fleet's instances now; the (self-declared) api_url isn't an auth
    # boundary anyway — the per-agent token is.
    result = await db.execute(
        select(Instance).where(
            Instance.api_url == body.api_url, Instance.fleet_id == fleet_id
        )
    )
    instance = result.scalar_one_or_none()

    if instance is None:
        instance = Instance(
            label=body.hostname,
            api_url=body.api_url,
            config_push_mode="agent",
            fleet_id=fleet_id,
            role="agent",
            agent_token_hash=token_hash,
        )
        db.add(instance)
    else:
        # Re-registration of same instance in same fleet — idempotent update
        instance.role = "agent"
        instance.agent_token_hash = token_hash
        db.add(instance)

    await db.commit()
    await db.refresh(instance)

    return RegisterAgentResponse(
        id=instance.id,
        label=instance.label,
        fleet_id=fleet_id,
        role=instance.role,
        agent_token=agent_token,
    )


@router.get("/{fleet_id}/bootstrap-command")
async def get_bootstrap_command(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    fleet = await _get_fleet_or_404(fleet_id, db)
    token_set = fleet.bootstrap_token_hash is not None
    command = (
        "curl -sL"
        + (' -H "X-Bootstrap-Token: <TOKEN>"' if token_set else "")
        + f" {{YOUR_VORTEXFLOW_URL}}/install/fleet/{fleet_id}"
        + " | sudo bash"
    )
    return {"command": command, "token_set": token_set}


async def _render_fleet(
    fleet_id: str, db: AsyncSession, reveal_secrets: bool = False
) -> config_render.RenderResult:
    """Load a fleet's components + routes and render them to a Vector config.

    ``reveal_secrets`` decrypts credential fields — pass it only when producing a
    config that actually runs (deploy) or is validated against the real values.
    The preview path leaves it False so secrets stay masked in the UI."""
    comp_result = await db.execute(
        select(Component)
        .where(Component.fleet_id == fleet_id)
        .order_by(Component.created_at)
    )
    components = list(comp_result.scalars().all())
    route_result = await db.execute(
        select(Route).where(Route.fleet_id == fleet_id).order_by(Route.created_at)
    )
    routes = list(route_result.scalars().all())
    stages, library_vrl = await _load_stages(fleet_id, db)
    # Resolve TLS cert-store refs to decrypted material only when revealing
    # (deploy/validate); the renderer turns these into managed paths + files.
    cert_materials = (
        await cert_delivery.materials_for_components(components, db)
        if reveal_secrets
        else None
    )
    return config_render.render_fleet_config(
        components,
        routes,
        stages,
        library_vrl,
        reveal_secrets=reveal_secrets,
        cert_materials=cert_materials,
    )


async def _load_stages(fleet_id: str, db: AsyncSession):
    """Load a fleet's remap stages + the VRL of any library templates they
    reference (resolved at render time)."""
    from app.models.transform_stage import TransformStage
    from app.models.vrl_transform import VrlTransform

    stages = list(
        (
            await db.execute(
                select(TransformStage)
                .where(TransformStage.fleet_id == fleet_id)
                .order_by(TransformStage.created_at)
            )
        )
        .scalars()
        .all()
    )
    ref_ids = {s.transform_id for s in stages if s.mode == "library" and s.transform_id}
    library_vrl: dict[str, str] = {}
    if ref_ids:
        rows = (
            (await db.execute(select(VrlTransform).where(VrlTransform.id.in_(ref_ids))))
            .scalars()
            .all()
        )
        library_vrl = {t.id: t.source_vrl for t in rows}
    return stages, library_vrl


@router.get("/{fleet_id}/config")
async def get_fleet_config(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> dict:
    """Preview the Vector config that would be deployed for this fleet."""
    await _get_fleet_or_404(fleet_id, db)
    result = await _render_fleet(fleet_id, db)
    return {
        "yaml": result.yaml,
        "warnings": result.warnings,
        "errors": result.errors,
    }


@router.get("/{fleet_id}/tap-targets")
async def fleet_tap_targets(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> dict:
    """Tappable Vector outputs for this fleet — what Live Tap can subscribe to.

    Returns each source, transform (remap), route, and route-branch output with
    its **rendered Vector id** (from the renderer's name_map, so it matches the
    deployed config exactly, collision suffixes and all) alongside the friendly
    label. Sinks are excluded — they have no outputs to tap."""
    await _get_fleet_or_404(fleet_id, db)
    comp_result = await db.execute(
        select(Component)
        .where(Component.fleet_id == fleet_id)
        .order_by(Component.created_at)
    )
    components = list(comp_result.scalars().all())
    route_result = await db.execute(
        select(Route).where(Route.fleet_id == fleet_id).order_by(Route.created_at)
    )
    routes = list(route_result.scalars().all())
    stages, library_vrl = await _load_stages(fleet_id, db)
    render = config_render.render_fleet_config(components, routes, stages, library_vrl)
    nm = render.name_map
    # Only list outputs that actually made it into the deployed config — the
    # renderer skips unwired/incomplete resources (orphan routes, remaps with no
    # VRL, etc.), and `name_map` includes those skipped ones. Tapping a component
    # Vector never instantiated would just hang with no events.
    rendered_sources = render.config.get("sources", {})
    rendered_transforms = render.config.get("transforms", {})

    targets: list[dict] = []
    for c in components:
        if c.kind == "source" and nm.get(c.id) in rendered_sources:
            targets.append(
                {"resource_id": c.id, "id": nm[c.id], "label": c.name, "kind": "source"}
            )
    for st in stages:
        if nm.get(st.id) in rendered_transforms:
            # input_ids = the rendered Vector ids of this transform's upstreams,
            # i.e. what Live Tap subscribes to for the "before" side of a
            # before/after compare. Only those that actually rendered.
            input_ids = [
                nm[iid]
                for iid in config_render._json_list(st.inputs_json)
                if nm.get(iid)
                and (nm[iid] in rendered_sources or nm[iid] in rendered_transforms)
            ]
            targets.append(
                {
                    "resource_id": st.id,
                    "id": nm[st.id],
                    "label": st.name,
                    "kind": "transform",
                    "input_ids": input_ids,
                }
            )
    for r in routes:
        rid = nm.get(r.id)
        if rid not in rendered_transforms:
            continue
        targets.append(
            {"resource_id": r.id, "id": rid, "label": r.name, "kind": "route"}
        )
        for b in config_render._json_list(r.branches_json):
            # Mirror the renderer: a branch is only emitted when it has BOTH a
            # name and a condition, so only those have a tappable output.
            if isinstance(b, dict) and b.get("name") and b.get("condition"):
                bn = config_render._safe_name(str(b["name"]))
                targets.append(
                    {
                        "resource_id": r.id,
                        "id": f"{rid}.{bn}",
                        "label": f"{r.name} → {b['name']}",
                        "kind": "route_branch",
                    }
                )
        if config_render._json_list(r.passthrough_sink_ids_json):
            targets.append(
                {
                    "resource_id": r.id,
                    "id": f"{rid}._unmatched",
                    "label": f"{r.name} → (unmatched)",
                    "kind": "route_branch",
                }
            )
    return {"targets": targets}


@router.post("/{fleet_id}/validate")
async def validate_fleet_config(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
) -> dict:
    """Run `vector validate` against this fleet's rendered config, server-side.

    Returns the render-level blocking errors/warnings plus Vector's own verdict
    (`valid` / `invalid` / `unavailable`). Catches schema mistakes the renderer
    can't — the same check the pre-deploy gate uses."""
    await _get_fleet_or_404(fleet_id, db)
    # Validate the *real* config (secrets revealed) so the verdict matches what
    # deploy will write. validate_config uses a private temp file, scrubbed.
    render = await _render_fleet(fleet_id, db, reveal_secrets=True)
    result = config_render.validate_config(
        render.yaml, redact=config_render.collect_secret_values(render.config)
    )
    return {
        "status": result.status,
        "output": result.output,
        "errors": render.errors,
        "warnings": render.warnings,
    }


@router.post("/{fleet_id}/deploy")
async def deploy_fleet(
    fleet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Publish the fleet config to every member instance.

    Bumps the fleet's published `generation`. Local-mode instances get the
    config written to their watched `config_dir` immediately. Agent-mode
    instances pull the published generation on their next poll and converge —
    reported here as `pending`.
    """
    fleet = await _get_fleet_or_404(fleet_id, db)
    # Deploy writes the real config to hosts — reveal the encrypted secrets.
    render = await _render_fleet(fleet_id, db, reveal_secrets=True)

    # Refuse to publish a config with blocking errors (e.g. listener bind
    # collisions). These render fine but fail at Vector reload on every member,
    # so we never bump the generation — agents stay on the last good config.
    if render.errors:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Config has blocking errors; deploy refused.",
                "errors": render.errors,
            },
        )

    # Pre-flight: run `vector validate` server-side. Block on a genuine schema
    # rejection; if Vector isn't available here, validation is skipped (the
    # agent still validates before reload in agent mode).
    validation = config_render.validate_config(
        render.yaml, redact=config_render.collect_secret_values(render.config)
    )
    if validation.status == "invalid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "vector validate rejected the config; deploy refused.",
                "errors": [validation.output or "vector validate failed"],
            },
        )

    # Snapshot the validated, secret-revealed render. Agents are served THIS
    # (decrypted at request time), never a live DB render — so an editor's
    # un-deployed edit can no longer reach a host. Encrypted at rest: it holds
    # decrypted secrets and cert private keys. Only a successful deploy writes it.
    fleet.deployed_config = deployed_config.encode(
        render.config, render.files, render.warnings, settings.secret_key
    )
    # Publish a new generation. Agents compare this to their applied generation.
    fleet.generation = (fleet.generation or 0) + 1
    db.add(fleet)

    inst_result = await db.execute(
        select(Instance)
        .where(Instance.fleet_id == fleet_id)
        .order_by(Instance.created_at)
    )
    instances = inst_result.scalars().all()

    # Deliver referenced TLS cert files to the host filesystem once (the managed
    # paths are keyed by component id, identical for every local-mode member on
    # the shared filesystem). Written before the configs that point at them.
    has_local = any(i.config_push_mode != "agent" and i.config_dir for i in instances)
    if render.files and has_local:
        cert_delivery.write_files_local(render.files)

    results: list[dict] = []
    for inst in instances:
        entry: dict = {"instance_id": inst.id, "label": inst.label}
        if inst.config_push_mode == "agent":
            entry.update(
                status="pending",
                detail=f"Agent will converge to generation {fleet.generation} on next poll",
            )
        elif not inst.config_dir:
            entry.update(
                status="error", detail="No config_dir set for local-mode instance"
            )
        else:
            try:
                content = config_render.serialize_with_globals(
                    render.config,
                    data_dir=inst.data_dir,
                    expire_metrics_secs=inst.expire_metrics_secs,
                )
                path = config_render.write_local_config(inst.config_dir, content)
                entry.update(status="deployed", path=path)
            except (OSError, ValueError):
                # Don't leak filesystem internals in the API response.
                entry.update(status="error", detail="Failed to write config to disk")
        results.append(entry)

    await db.commit()

    deployed = sum(1 for r in results if r["status"] == "deployed")
    pending = sum(1 for r in results if r["status"] == "pending")
    await audit.record(
        action="fleet.deploy",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="fleet",
        resource_id=fleet_id,
        detail=f"'{fleet.name}' → generation {fleet.generation}: "
        f"{deployed} deployed, {pending} pending",
    )
    return {
        "deployed": deployed,
        "pending": pending,
        "total": len(results),
        "generation": fleet.generation,
        "warnings": render.warnings,
        "results": results,
    }


async def _get_fleet_or_404(fleet_id: str, db: AsyncSession) -> Fleet:
    result = await db.execute(select(Fleet).where(Fleet.id == fleet_id))
    fleet = result.scalar_one_or_none()
    if not fleet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found"
        )
    return fleet


async def _get_instance_or_404(instance_id: str, db: AsyncSession) -> Instance:
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found"
        )
    return instance
