from __future__ import annotations

from sqlalchemy import create_engine as _sync_create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from crypto_trader.persistence.models import Base


def create_db_engine(database_url: str, **kwargs) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        # Let concurrent readers/writers wait for the single-writer lock instead
        # of immediately raising "database is locked" under contention.
        kwargs.setdefault("connect_args", {"timeout": 30.0})
    engine = create_async_engine(database_url, pool_pre_ping=True, **kwargs)
    if database_url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            # WAL lets readers proceed while a writer holds the lock: the
            # runtime's event loop, API reads, and harness queries no longer
            # spuriously fail with 'database is locked'. busy_timeout adds a
            # bounded retry for the remaining write-write contention.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

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
