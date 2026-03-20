"""Async SQLAlchemy database setup.

Supports both SQLite (dev default) and PostgreSQL (production/multi-user).
Set DATABASE_URL or db_url in .env to switch.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Engine kwargs differ between SQLite and PostgreSQL
_engine_kwargs: dict = {"echo": False}
if settings.db_url.startswith("sqlite"):
    # SQLite: needs check_same_thread for async
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL: connection pool settings
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
    _engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(settings.db_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        yield session
