# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Alembic environment for VortexFlow.

The DB URL comes from application settings (single source of truth), and every
model module is imported explicitly so ``Base.metadata`` is fully populated —
``app.models.__init__`` intentionally re-exports only a subset, which is NOT
enough for autogenerate (it would try to drop the un-imported tables).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import Base

# ── populate Base.metadata: import EVERY model module ────────────────────────
# Imported programmatically (not a hand-kept list) so a newly added model file
# can't be silently omitted — the `alembic check` drift gate only sees tables
# whose module is imported here, so a missed import would let a new table ship
# with no migration. This is exactly the hand-list failure mode the retired
# Sentinel C2 check had; don't reintroduce it as an explicit import block.
import importlib  # noqa: E402
import pkgutil  # noqa: E402

import app.models as _models_pkg  # noqa: E402

for _module in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"{_models_pkg.__name__}.{_module.name}")

config = context.config
# Only configure logging on the CLI path. When the app drives migrations at
# startup (config.attributes["connection"] is set), the process already has
# uvicorn/app logging configured — fileConfig() would disable those loggers
# (its default disable_existing_loggers=True silences every logger not named
# in alembic.ini, including the fresh-install recovery-token warning).
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Application settings are authoritative for the connection URL.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB (``alembic upgrade --sql``)."""
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # The app injects its own (sync) Connection when running migrations on
    # startup (see app.main._run_migrations); the CLI path builds its own engine.
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        _do_run_migrations(connectable)
    else:
        asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
