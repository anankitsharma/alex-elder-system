"""Alembic environment — async support for SQLite and PostgreSQL."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Alembic Config object
config = context.config

# Setup Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic sees them for autogenerate
from app.database import Base
from app.models.market import Instrument, Candle, RolloverHistory  # noqa
from app.models.trade import Order, Position, Trade  # noqa
from app.models.signal import Signal  # noqa
from app.models.config import ConfigEntry, PortfolioRisk  # noqa
from app.models.user import (  # noqa
    User, Role, Permission, UserBrokerCredentials,
    UserNotificationConfig, AccessRequest, role_permissions,
)
from app.models.audit import AuditLog  # noqa

target_metadata = Base.metadata

# Override sqlalchemy.url from app config (so .env is the single source of truth)
from app.config import settings

# Alembic needs a sync URL for offline mode, async for online
_db_url = settings.db_url
# For async online migrations, we use the async URL directly
# For offline (SQL generation), strip the async driver
_sync_url = _db_url.replace("+asyncpg", "").replace("+aiosqlite", "")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without connecting)."""
    context.configure(
        url=_sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Required for SQLite ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # Required for SQLite ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _db_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
