# Phase 1: PostgreSQL Migration + Alembic

## Why PostgreSQL First

SQLite uses a **database-level write lock**. With 2+ users placing orders while the pipeline writes candles, you'll get `database is locked` errors. PostgreSQL's MVCC allows 100+ concurrent writers.

## Changes

### 1.1 Install Dependencies

```bash
pip install asyncpg psycopg2-binary alembic
```

### 1.2 Update `config.py`

```python
# Replace:
db_url: str = "sqlite+aiosqlite:///./elder_trading.db"

# With:
db_url: str = "postgresql+asyncpg://elder:elder@localhost:5432/elder_trading"
db_url_sync: str = "postgresql+psycopg2://elder:elder@localhost:5432/elder_trading"  # For Alembic
```

Keep SQLite as fallback for local dev:
```python
db_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./elder_trading.db")
```

### 1.3 Update `database.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# AsyncPG for PostgreSQL, aiosqlite for SQLite (dev)
engine = create_async_engine(settings.db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
```

### 1.4 Initialize Alembic

```bash
cd backend
alembic init alembic
```

Configure `alembic/env.py` to use async engine and import all models.

### 1.5 Data Migration

```bash
# Export from SQLite
sqlite3 elder_trading.db .dump > dump.sql

# Import to PostgreSQL (with minor SQL syntax fixes)
psql -d elder_trading < dump.sql
```

Or use `pgloader` for automatic migration:
```bash
pgloader elder_trading.db postgresql://elder:elder@localhost/elder_trading
```

### 1.6 PostgreSQL Setup (Docker)

```yaml
# docker-compose.yml (for local dev)
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: elder
      POSTGRES_PASSWORD: elder
      POSTGRES_DB: elder_trading
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

## Verification

```bash
pytest tests/ -x -q  # All existing tests must pass against PostgreSQL
```

## Rollback

Keep SQLite config as fallback. Both engines work with SQLAlchemy ORM — no SQL syntax changes needed.
