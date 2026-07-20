# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router
import app.models.system_setting  # noqa: F401 — registers SystemSetting with Base.metadata
import app.models.certificate  # noqa: F401 — registers Certificate with Base.metadata
import app.models.event  # noqa: F401 — registers Event with Base.metadata
import app.models.notification  # noqa: F401 — registers notification tables
import app.models.transform_stage  # noqa: F401 — registers TransformStage
import app.models.api_token  # noqa: F401 — registers ApiToken with Base.metadata
from app.api.install import router as install_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _run_migrations()
    await _migrate_component_secrets()
    await _bootstrap_admin()
    await _bootstrap_default_fleet()
    _bootstrap_tls()

    # One-time setup / break-glass recovery token — stored in Redis, single-use,
    # 1h TTL. Armed only when genuinely needed (a fresh install with no admin
    # yet, or an explicit opt-in for a locked-out-admin recovery) so a fresh
    # admin-granting token is not printed to the logs on every restart.
    if await _needs_recovery_token():
        token = secrets.token_urlsafe(32)
        from app.api.v1.recovery import set_recovery_token

        await set_recovery_token(token)
        logger.warning(f"SETUP / RECOVERY TOKEN (single-use, 1h): {token}")

    # Background worker: detect events + deliver notifications independent of the
    # UI, so alerts fire even when no dashboard is open.
    worker = asyncio.create_task(_notification_worker())
    # Background worker: prune unbounded operational tables on a daily sweep.
    retention = asyncio.create_task(_retention_worker())

    yield

    for task in (worker, retention):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await engine.dispose()


app = FastAPI(
    title="VortexFlow",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    """Browser origins allowed to call the API with credentials.

    Because ``allow_credentials=True`` cannot combine with a ``*`` wildcard, the
    list is explicit: the configured ``public_url`` (the same-origin UI), any
    operator-supplied ``cors_origins``, and — only in debug — the localhost dev
    origins (the Vite dev server proxies ``/api``, so these are just for direct
    API access). A production build ships none of the dev origins."""
    origins: list[str] = []
    if settings.public_url:
        origins.append(settings.public_url.rstrip("/"))
    origins += [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.debug:
        origins += ["http://localhost:5173", "http://localhost:3000"]
    # De-duplicate, preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            unique.append(o)
    return unique


app.add_middleware(  # type: ignore[attr-defined]
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")  # type: ignore[attr-defined]
app.include_router(install_router, prefix="/install", tags=["install"])  # type: ignore[attr-defined]


@app.get("/api/v1/health")  # type: ignore[attr-defined]
async def health():
    return {"status": "ok", "app": settings.app_name}


async def _notification_worker():
    """Every ``tick_interval_secs`` (notifications setting, default 30): reconcile
    fleet events and drain the notification outbox. The single delivery driver."""
    from app.core.database import AsyncSessionLocal
    from app.api.v1.settings import _get_setting
    from app.services.event_detector import detect_and_record
    from app.services.notify import enqueue_deliveries, dispatch_pending

    while True:
        interval = 30
        try:
            async with AsyncSessionLocal() as db:
                notif = await _get_setting("notifications", db)
                interval = int(notif.get("tick_interval_secs") or 30)
                opened, resolved = await detect_and_record(db)
                await enqueue_deliveries(db, opened, resolved)
                await dispatch_pending(db)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — keep the worker alive
            logger.warning(f"notification worker iteration failed: {e}")
        await asyncio.sleep(max(5, interval))


async def _retention_worker():
    """Daily sweep: prune operational tables past their configured retention.

    No-op unless an operator sets a retention (audit/event/notification days),
    so it's cheap and safe by default. Interval is ``retention_sweep_hours``.
    """
    from app.core.config import settings as _settings
    from app.core.database import AsyncSessionLocal
    from app.services.retention import prune_old_records

    await asyncio.sleep(60)  # let startup settle before the first sweep
    while True:
        try:
            async with AsyncSessionLocal() as db:
                counts = await prune_old_records(db)
            if counts:
                logger.info("retention sweep pruned: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — keep the worker alive
            logger.warning(f"retention sweep failed: {e}")
        await asyncio.sleep(max(1, _settings.retention_sweep_hours) * 3600)


async def _legacy_ensure_baseline():
    """Idempotently bring a PRE-ALEMBIC database up to the 0001 baseline schema.

    Runs only during the one-time cutover for installs provisioned by the
    original startup-DDL mechanism (detected by a missing ``alembic_version``
    table in ``_run_migrations``). Every statement is a no-op on an
    already-current DB, so a direct upgrade from ANY prior version lands exactly
    at the baseline before Alembic takes over.

    New schema changes are Alembic migrations now — do NOT add columns here.
    Generate one with ``make migration m="..."`` after editing the models.
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        # ── stream → fleet rename (P4) ──────────────────────────────────────
        # Must run BEFORE create_all so the existing table/columns are renamed
        # in place and reused — otherwise create_all would build an empty
        # `fleets` table beside the data-bearing `streams`. Idempotent: each
        # block only fires when the old name exists and the new one doesn't, so
        # it's a no-op on already-migrated and brand-new databases alike.
        # Postgres auto-rewrites FK references across RENAME.
        await conn.execute(
            text(
                "DO $$ BEGIN"
                " IF EXISTS (SELECT FROM information_schema.tables"
                " WHERE table_name='streams')"
                " AND NOT EXISTS (SELECT FROM information_schema.tables"
                " WHERE table_name='fleets')"
                " THEN ALTER TABLE streams RENAME TO fleets; END IF; END $$;"
            )
        )
        for _tbl in ("instances", "routes", "components", "transform_stages"):
            await conn.execute(
                text(
                    "DO $$ BEGIN"
                    f" IF EXISTS (SELECT FROM information_schema.columns"
                    f" WHERE table_name='{_tbl}' AND column_name='stream_id')"
                    f" AND NOT EXISTS (SELECT FROM information_schema.columns"
                    f" WHERE table_name='{_tbl}' AND column_name='fleet_id')"
                    f" THEN ALTER TABLE {_tbl} RENAME COLUMN stream_id TO fleet_id;"
                    " END IF; END $$;"
                )
            )
        # ────────────────────────────────────────────────────────────────────
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS fleet_id VARCHAR"
                " REFERENCES fleets(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS role VARCHAR"
                " NOT NULL DEFAULT 'agent'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE routes ADD COLUMN IF NOT EXISTS source_ids_json TEXT"
                " NOT NULL DEFAULT '[]'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE routes ADD COLUMN IF NOT EXISTS"
                " passthrough_sink_ids_json TEXT NOT NULL DEFAULT '[]'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS"
                " tls_verify BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        await conn.execute(
            text("ALTER TABLE instances ADD COLUMN IF NOT EXISTS tls_ca_cert TEXT")
        )
        await conn.execute(
            text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS eku TEXT")
        )
        await conn.execute(
            text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS ca_chain_pem TEXT")
        )
        await conn.execute(
            text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS notes TEXT")
        )
        await conn.execute(
            text("ALTER TABLE instances ADD COLUMN IF NOT EXISTS data_dir VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS"
                " expire_metrics_secs INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS"
                " generation INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS"
                " desired_vector_version VARCHAR"
            )
        )
        await conn.execute(
            text("ALTER TABLE fleets ADD COLUMN IF NOT EXISTS deployed_config TEXT")
        )
        await conn.execute(
            text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS secrets_encrypted TEXT"
            )
        )
        await conn.execute(
            text("ALTER TABLE components ADD COLUMN IF NOT EXISTS cert_refs_json TEXT")
        )
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS"
                " applied_generation INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS"
                " agent_last_seen TIMESTAMPTZ"
            )
        )
        await conn.execute(
            text("ALTER TABLE instances ADD COLUMN IF NOT EXISTS agent_status VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE instances ADD COLUMN IF NOT EXISTS vector_version VARCHAR"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS"
                " must_change_password BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS"
                " inputs_json TEXT NOT NULL DEFAULT '[]'"
            )
        )
        # At most one *unresolved* event per dedup_key (idempotent detection).
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_events_open_dedup_key"
                " ON events (dedup_key) WHERE resolved_at IS NULL"
            )
        )
        # One delivery per (event, channel, transition) — idempotent enqueue.
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_deliveries_event_channel_trans"
                " ON notification_deliveries (event_id, channel_id, transition)"
            )
        )


def _alembic_config(connection):
    """Alembic Config wired to an existing (sync) Connection so startup
    migrations reuse the app engine instead of opening a second one. Paths are
    resolved from this file so it works regardless of the process cwd."""
    from pathlib import Path

    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent  # app/ -> backend/
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


async def _run_migrations():
    """Bring the DB schema to Alembic head.

    Handles the one-time cutover from the pre-Alembic startup-DDL mechanism:
    a database that has application tables but no ``alembic_version`` is first
    brought fully up to the baseline (``_legacy_ensure_baseline``), then stamped
    at the baseline revision so Alembic adopts it without re-creating anything.
    Fresh and already-Alembic-managed databases skip straight to ``upgrade head``.
    """
    from alembic import command
    from sqlalchemy import inspect

    def _probe(sync_conn):
        insp = inspect(sync_conn)
        return insp.has_table("alembic_version"), insp.has_table("users")

    async with engine.connect() as conn:
        managed, provisioned = await conn.run_sync(_probe)

    if not managed and provisioned:
        logger.info("adopting Alembic on a pre-Alembic database — stamping baseline")
        await _legacy_ensure_baseline()
        async with engine.connect() as conn:
            await conn.run_sync(
                lambda c: command.stamp(_alembic_config(c), "0001_baseline")
            )

    async with engine.connect() as conn:
        await conn.run_sync(lambda c: command.upgrade(_alembic_config(c), "head"))


def _bootstrap_tls():
    """Generate a self-signed CA + server cert on first boot when a shared TLS
    cert dir is configured. No-op if a cert already exists or the dir is unset."""
    if not settings.tls_cert_dir:
        return
    from app.services.tls_bootstrap import ensure_self_signed

    try:
        ensure_self_signed(settings.tls_cert_dir, settings.public_url)
    except Exception as e:
        logger.error(f"TLS bootstrap failed: {e}")


async def _migrate_component_secrets():
    """One-time: pull plaintext credentials out of existing components'
    config_json into the encrypted secrets_encrypted column. Idempotent — a
    component is only rewritten while its config_json still holds secret-keyed
    fields, so this is a no-op once migrated (and on fresh installs)."""
    import json as _json

    from sqlalchemy import select

    from app.core.config import settings as _settings
    from app.core.database import AsyncSessionLocal
    from app.models.component import Component
    from app.services import secrets as secrets_svc

    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Component))).scalars().all()
            changed = 0
            for c in rows:
                try:
                    config = _json.loads(c.config_json or "{}")
                except (_json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(config, dict):
                    continue
                if not any(secrets_svc.is_secret_key(k) for k in config):
                    continue  # nothing left to migrate
                try:
                    public, secrets_enc = secrets_svc.split_for_write(
                        config, c.secrets_encrypted, _settings.at_rest_key
                    )
                except ValueError as e:
                    # A stored MASK-placeholder value (or a masked reference to a
                    # secret encrypted under a different key — e.g. encryption_key
                    # set before `reencrypt_secrets` was run) can't be split. Skip
                    # this component rather than aborting, but log it so the skip
                    # isn't silent.
                    logger.warning(
                        "component secret migration skipped component %s: %s", c.id, e
                    )
                    continue
                c.config_json = _json.dumps(public)
                if secrets_enc is not None:
                    c.secrets_encrypted = secrets_enc
                changed += 1
            if changed:
                await db.commit()
                logger.info(f"encrypted credentials in {changed} component(s)")
    except Exception as e:  # pragma: no cover - defensive, never block startup
        logger.warning(f"component secret migration skipped: {e}")


async def _bootstrap_admin():
    """Seed the admin account.

    **Demo mode:** create the documented default-credential admin — the
    auto-registering demo agent and the documented login rely on it.

    **Real install:** do NOT seed a static-password admin. A well-known default
    credential is a poor security posture for a public tool. Instead the operator
    creates the first admin with the one-time **setup token** printed to the logs
    at startup (POST it to ``/recovery`` with a chosen password). See
    :func:`app.api.v1.recovery.use_recovery`."""
    from sqlalchemy import select, func
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.core.security import get_password_hash

    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        if count != 0:
            return
        if not settings.demo_mode:
            logger.warning(
                "No users yet — create the first admin with the one-time setup "
                "token in the logs (look for 'SETUP / RECOVERY TOKEN'); POST it "
                "to %s/recovery with a chosen password.",
                settings.public_url or "",
            )
            return
        admin = User(
            email=settings.bootstrap_admin_email,
            name=settings.bootstrap_admin_name,
            hashed_password=get_password_hash(settings.bootstrap_admin_password),
            role="admin",
            auth_method="local",
            is_active=True,
            must_change_password=False,  # demo: documented creds are expected
        )
        session.add(admin)
        await session.commit()
        logger.info(f"Demo admin created: {settings.bootstrap_admin_email}")


async def _needs_recovery_token() -> bool:
    """Whether to arm the setup/recovery token at startup.

    True on a fresh install (no active admin account yet) or when explicitly
    opted in via ``enable_recovery_token``. Steady-state restarts with a working
    admin never print an admin-granting token to the logs.
    """
    if settings.enable_recovery_token:
        return True
    from sqlalchemy import func, select
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as session:
        active_admins = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
    return not active_admins


async def _bootstrap_default_fleet():
    """Create a default fleet if none exists."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.fleet import Fleet

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(Fleet).where(Fleet.is_default == True).limit(1)  # noqa: E712
        )
        if not existing:
            fleet = Fleet(name="Default", is_default=True, created_by=None)
            session.add(fleet)
            await session.commit()
            logger.info("Bootstrap default fleet created")
