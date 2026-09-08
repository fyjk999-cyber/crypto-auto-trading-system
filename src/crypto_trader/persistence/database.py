from __future__ import annotations

from sqlalchemy import create_engine as _sync_create_engine
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from crypto_trader.persistence.models import Base

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA busy_timeout=15000;",
    "PRAGMA synchronous=NORMAL;",
)


def _sqlite_connect_pragmas(dbapi_conn, _record) -> None:
    """Per-connection SQLite tuning.

    The execution lease is renewed on a 3s cadence while audit/decision
    writers run continuously. Without WAL + a long busy timeout, renewal
    transactions hit SQLITE_BUSY and the engine fails SAFE (kill switch,
    no trades). busy_timeout/journal_mode are per-connection, so they must
    be applied to every pooled connection at connect time.
    """
    try:
        cursor = dbapi_conn.cursor()
        for statement in _SQLITE_PRAGMAS:
            cursor.execute(statement)
        cursor.close()
    except Exception:
        pass  # non-sqlite dialect or read-only file: pragmas are best-effort


def create_db_engine(database_url: str, **kwargs) -> AsyncEngine:
    engine = create_async_engine(database_url, pool_pre_ping=True, **kwargs)
    if database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _sqlite_connect_pragmas)
    return engine


class Database:
    def __init__(self, database_url: str, **engine_kwargs) -> None:
        self.url = database_url
        self.engine: AsyncEngine = create_db_engine(database_url, **engine_kwargs)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def close(self) -> None:
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.session_factory()


def create_sync_engine(database_url: str):
    """Synchronous engine for Alembic migrations."""
    return _sync_create_engine(
        database_url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")
    )
