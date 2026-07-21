# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""VortexFlow MCP server (read-only v1).

Exposes a curated, read-only view of a VortexFlow deployment over the Model
Context Protocol (streamable HTTP, mounted at /mcp) plus the `validate_vrl`
primitive. Every tool authenticates a personal access token and calls the SAME
service functions as the REST API (`vrl_runner`, `config_render` via the fleets
route helper) — no duplicated logic, so there is nothing to drift.

Writes (create/update components, deploy) are a deliberate, RBAC-gated
follow-up; nothing here mutates state.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any, Literal

import json

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy import func, select

from app.mcp.auth import McpAuthError, authed_session, require_user
from app.models.component import Component
from app.models.fleet import Fleet
from app.models.instance import Instance
from app.models.route import Route
from app.models.transform_stage import TransformStage
from app.models.vrl_transform import VrlTransform
from app.services.redis_client import check_rate_limit
from app.services.vrl_runner import run_vrl

logger = logging.getLogger(__name__)

_CATALOG_TYPES = Path(__file__).resolve().parent.parent / "data" / "catalog_types.json"

# Per-user cap for the VRL validate tool, SHARING the REST key so a caller can't
# double their subprocess budget by splitting load across MCP and the REST API.
_VRL_RATE_LIMIT = 60  # requests/min per user — matches /transforms/validate


def _guard(fn):
    """Let intended errors (auth failures, not-found, rate-limit) reach the
    caller verbatim, but collapse any UNEXPECTED exception (DB driver text,
    subprocess internals) into a generic message so it can't leak infrastructure
    detail — even though the caller is already authenticated."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (McpAuthError, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001 — genericize, don't leak
            logger.warning("MCP tool %s failed: %s", fn.__name__, exc)
            raise ValueError(f"internal error in {fn.__name__}") from None

    return wrapper


mcp = FastMCP(
    "VortexFlow",
    instructions=(
        "Read-only access to a VortexFlow deployment (a management UI for Vector "
        "data pipelines). Inspect fleets, components (sources/sinks), routes, VRL "
        "transforms, the accepted source/sink catalog, and the rendered Vector "
        "config; validate VRL programs against Vector's compiler. Authenticate "
        "with a VortexFlow personal access token: `Authorization: Bearer "
        "vf_pat_...`. All tools are read-only."
    ),
    stateless_http=True,
    streamable_http_path="/",
)


async def _fleet_or_error(db, fleet_id: str) -> Fleet:
    fleet = (
        await db.execute(select(Fleet).where(Fleet.id == fleet_id))
    ).scalar_one_or_none()
    if fleet is None:
        raise ValueError(f"no fleet with id {fleet_id!r}")
    return fleet


# ── VRL ───────────────────────────────────────────────────────────────────────
@mcp.tool()
@_guard
async def validate_vrl(
    source: str, ctx: Context, event: dict[str, Any] | None = None
) -> dict:
    """Validate/execute a VRL program against Vector's compiler and return the
    diagnostics. `event` is a sample event the program runs against (defaults to
    an empty object). Use this to check VRL before saving it as a transform."""
    # Auth only (no DB needed past this point); release the connection before the
    # subprocess. Rate-limited per user (shared with the REST validate endpoint)
    # so an authed caller can't spawn unbounded concurrent `vector` subprocesses.
    user = await require_user(ctx)
    if not await check_rate_limit(f"vrl_validate_rate:{user.id}", _VRL_RATE_LIMIT):
        raise ValueError("VRL validate rate limit exceeded — max 60 requests/minute.")
    result = await run_vrl(source, event or {})
    return {"ok": result.ok, "output": result.output, "error": result.error}


# ── fleets ──────────────────────────────────────────────────────────────────
@mcp.tool()
@_guard
async def list_fleets(ctx: Context) -> list[dict]:
    """List all fleets (named groups of Vector instances sharing one config),
    with their current config generation and member/component counts."""
    async with authed_session(ctx) as (db, _user):
        fleets = list((await db.execute(select(Fleet))).scalars().all())
        out = []
        for f in fleets:
            members = await db.scalar(
                select(func.count())
                .select_from(Instance)
                .where(Instance.fleet_id == f.id)
            )
            components = await db.scalar(
                select(func.count())
                .select_from(Component)
                .where(Component.fleet_id == f.id)
            )
            out.append(
                {
                    "id": f.id,
                    "name": f.name,
                    "description": f.description,
                    "is_default": f.is_default,
                    "generation": f.generation,
                    "desired_vector_version": f.desired_vector_version,
                    "instances": members or 0,
                    "components": components or 0,
                }
            )
        return out


@mcp.tool()
@_guard
async def get_fleet(fleet_id: str, ctx: Context) -> dict:
    """Get one fleet with a summary of its components, routes, and transform
    stages. Use `render_fleet_config` for the full Vector YAML it deploys."""
    async with authed_session(ctx) as (db, _user):
        fleet = await _fleet_or_error(db, fleet_id)
        components = list(
            (await db.execute(select(Component).where(Component.fleet_id == fleet_id)))
            .scalars()
            .all()
        )
        routes = list(
            (await db.execute(select(Route).where(Route.fleet_id == fleet_id)))
            .scalars()
            .all()
        )
        stages = list(
            (
                await db.execute(
                    select(TransformStage).where(TransformStage.fleet_id == fleet_id)
                )
            )
            .scalars()
            .all()
        )
        return {
            "id": fleet.id,
            "name": fleet.name,
            "description": fleet.description,
            "is_default": fleet.is_default,
            "generation": fleet.generation,
            "desired_vector_version": fleet.desired_vector_version,
            "sources": [c.name for c in components if c.kind == "source"],
            "sinks": [c.name for c in components if c.kind == "sink"],
            "routes": [r.name for r in routes],
            "transform_stages": [s.name for s in stages],
        }


@mcp.tool()
@_guard
async def list_components(fleet_id: str, ctx: Context) -> list[dict]:
    """List a fleet's components (Vector sources and sinks) with their type and
    the ids of the components/stages that feed each one."""
    async with authed_session(ctx) as (db, _user):
        await _fleet_or_error(db, fleet_id)
        components = list(
            (
                await db.execute(
                    select(Component)
                    .where(Component.fleet_id == fleet_id)
                    .order_by(Component.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": c.id,
                "kind": c.kind,  # source | sink
                "name": c.name,
                "type": c.component_type,  # e.g. kafka, http, file
            }
            for c in components
        ]


@mcp.tool()
@_guard
async def list_routes(fleet_id: str, ctx: Context) -> list[dict]:
    """List a fleet's routes (conditional branching transforms) with their branch
    names."""
    async with authed_session(ctx) as (db, _user):
        await _fleet_or_error(db, fleet_id)
        routes = list(
            (
                await db.execute(
                    select(Route)
                    .where(Route.fleet_id == fleet_id)
                    .order_by(Route.created_at)
                )
            )
            .scalars()
            .all()
        )
        out = []
        for r in routes:
            try:
                branches = json.loads(getattr(r, "branches_json", "[]") or "[]")
                branch_names = [b.get("name") for b in branches if isinstance(b, dict)]
            except (json.JSONDecodeError, TypeError):
                branch_names = []
            out.append({"id": r.id, "name": r.name, "branches": branch_names})
        return out


@mcp.tool()
@_guard
async def render_fleet_config(fleet_id: str, ctx: Context) -> dict:
    """Render the Vector YAML config VortexFlow would deploy for this fleet.
    Secrets are masked (this is a preview, not the deployed material). Returns the
    YAML plus advisory render warnings AND blocking errors — a non-empty `errors`
    list means deploy would refuse this config; consult it before treating the
    YAML as deploy-ready."""
    # Reuse the exact renderer the REST deploy/preview path uses (single source of
    # truth). Import lazily to avoid a module-load cycle through the API package.
    from app.api.v1.fleets import _render_fleet

    async with authed_session(ctx) as (db, _user):
        await _fleet_or_error(db, fleet_id)
        result = await _render_fleet(fleet_id, db, reveal_secrets=False)
    return {"yaml": result.yaml, "warnings": result.warnings, "errors": result.errors}


# ── transforms + catalog ────────────────────────────────────────────────────
@mcp.tool()
@_guard
async def list_transforms(ctx: Context) -> list[dict]:
    """List the reusable VRL transform library (saved, named VRL programs)."""
    async with authed_session(ctx) as (db, _user):
        transforms = list(
            (await db.execute(select(VrlTransform).order_by(VrlTransform.name)))
            .scalars()
            .all()
        )
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": getattr(t, "description", None),
                "source_vrl": t.source_vrl,
            }
            for t in transforms
        ]


@mcp.tool()
@_guard
async def get_catalog(
    ctx: Context, kind: Literal["source", "sink"] | None = None
) -> dict:
    """List the Vector source/sink types this deployment accepts (the component
    catalog). `kind` filters to "source" or "sink"; omit for both."""
    await require_user(ctx)  # auth only; the catalog is a static file, no DB
    data = json.loads(_CATALOG_TYPES.read_text(encoding="utf-8"))
    catalog = {
        "schema_version": data.get("schema_version"),
        "sources": data.get("sources", []),
        "sinks": data.get("sinks", []),
    }
    if kind in ("source", "sources"):
        return {
            "schema_version": catalog["schema_version"],
            "sources": catalog["sources"],
        }
    if kind in ("sink", "sinks"):
        return {"schema_version": catalog["schema_version"], "sinks": catalog["sinks"]}
    return catalog


# ── instances ───────────────────────────────────────────────────────────────
@mcp.tool()
@_guard
async def list_instances(ctx: Context, fleet_id: str | None = None) -> list[dict]:
    """List Vector instances, optionally scoped to one fleet. Includes each
    instance's role, agent status, and config-generation lag (applied vs. the
    fleet's current generation) so you can see what hasn't converged."""
    async with authed_session(ctx) as (db, _user):
        stmt = select(Instance)
        if fleet_id is not None:
            await _fleet_or_error(db, fleet_id)
            stmt = stmt.where(Instance.fleet_id == fleet_id)
        instances = list((await db.execute(stmt)).scalars().all())
        # Fleet generations for lag computation.
        gen_rows = (await db.execute(select(Fleet.id, Fleet.generation))).all()
        gens: dict[str, int] = {row[0]: row[1] for row in gen_rows}
        return [
            {
                "id": i.id,
                "label": i.label,
                "fleet_id": i.fleet_id,
                "role": i.role,
                "config_push_mode": i.config_push_mode,
                "is_active": i.is_active,
                "agent_status": i.agent_status,
                "agent_last_seen": (
                    i.agent_last_seen.isoformat() if i.agent_last_seen else None
                ),
                "vector_version": i.vector_version,
                "applied_generation": i.applied_generation,
                "fleet_generation": (
                    gens.get(i.fleet_id) if i.fleet_id is not None else None
                ),
                "up_to_date": (
                    i.fleet_id is not None
                    and i.applied_generation is not None
                    and i.applied_generation == gens.get(i.fleet_id)
                ),
            }
            for i in instances
        ]


def build_asgi_app():
    """The streamable-HTTP ASGI app to mount at /mcp. Mounting also lazily creates
    the session manager; `app.main` runs it in the FastAPI lifespan."""
    return mcp.streamable_http_app()
