"""Database-backed single-writer run lease.

PORTED from the reference v2 run-lease semantics:
- exactly one live execution lease per lease_key
- renew/extend/expire/recover
- all writers must present a valid lease token

Implemented with an atomic CAS UPDATE so concurrent engine instances cannot
both acquire an expired lease.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, event, func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from crypto_trader.domain.errors import LeaseNotHeld, OrderRejected
from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import AuditEventORM, EngineRunORM, RuntimeLeaseORM


def _epoch(dt: datetime | None = None) -> float:
    return (dt or datetime.now(UTC)).timestamp()


def _install_sqlite_clock(connection, record, _proxy):
    if not record.info.get("execution_lease_clock"):
        # Evaluated by SQLite AFTER lock waits, not an old bound timestamp.
        connection.create_function("execution_lease_epoch", 0, lambda: _epoch())
        record.info["execution_lease_clock"] = True


def _db_epoch(session):
    if session.get_bind().dialect.name == "sqlite":
        return func.execution_lease_epoch()
    return func.extract("epoch", func.clock_timestamp())


@dataclass(frozen=True)
class Lease:
    lease_key: str
    owner_id: str
    token: str
    expires_at: float
    fence_generation: int = 1


class _FencedSyncSession(Session):
    pass


class _FencedSession(AsyncSession):
    def __init__(self, *args, lease_provider, lease_valid, run_id_provider, lease_failed, **kwargs):
        super().__init__(*args, sync_session_class=_FencedSyncSession, **kwargs)
        # Capture THIS actor/grant, not whatever owner exists after an await
        # or controlled restart. A stale session must never borrow a new grant.
        grant = lease_provider()
        self.info.update(writer_lease=grant,
                         writer_valid=lambda: lease_provider() is grant and lease_valid(),
                         writer_run_id=run_id_provider(),
                         writer_failed=lambda: lease_failed(grant))

    async def fence_writer_transaction(self):
        """Lock before reads used to derive writes, not only before their DML."""
        await self.run_sync(_fence_write)


def _requires_writer(session, obj):
    # Append-only failure evidence and own-run shutdown metadata cannot grant
    # trading authority. They remain writable after loss for forensic cleanup.
    if isinstance(obj, AuditEventORM) and obj in session.new:
        if obj.action in {"EXECUTION_LEASE_LOST", "ENGINE_STOPPED"}:
            return False
    if (isinstance(obj, EngineRunORM) and obj not in session.new
            and obj not in session.deleted):
        if obj.state == "STOPPED" and obj.run_id == session.info["writer_run_id"]:
            changed = {attr.key for attr in inspect(obj).attrs if attr.history.has_changes()}
            if changed <= {"state", "ended_at"}:
                return False
    return True


def _fence_write(session):
    lease = session.info["writer_lease"]
    if lease is None or not session.info["writer_valid"]():
        session.info["writer_failed"]()
        raise LeaseNotHeld("execution writer authority unavailable")
    # No-op UPDATE takes the DB writer/row lock in THIS mutation transaction.
    # Another holder cannot CAS ownership while our mutation is in flight.
    # SQL evaluates expiry AFTER any lock wait, and again before commit; expiry
    # aborts/rolls back the complete transaction rather than extending the TTL.
    try:
        result = session.connection().execute(update(RuntimeLeaseORM).where(
            RuntimeLeaseORM.lease_key == lease.lease_key,
            RuntimeLeaseORM.owner_id == lease.owner_id,
            RuntimeLeaseORM.token == lease.token,
            RuntimeLeaseORM.fence_generation == lease.fence_generation,
            RuntimeLeaseORM.expires_at > _db_epoch(session),
        ).values(version=RuntimeLeaseORM.version))
    except Exception:
        session.info["writer_failed"]()
        raise
    # Do not use RETURNING: cancellation before fetching its rows can retain
    # an active SQLite write cursor even after connection invalidation/close.
    # Matched-row count proves the execution-time owner/token/fence/expiry CAS.
    if result.rowcount != 1 or not session.info["writer_valid"]():
        session.info["writer_failed"]()
        raise LeaseNotHeld("execution writer lease expired or fenced")
    guard = session.info.get("execution_guard")
    if guard is not None:
        failures = guard()
        if failures:
            raise OrderRejected("TRADING_SAFETY_INVALID:" + ",".join(failures))
    session.info["writer_transaction"] = True


@event.listens_for(_FencedSyncSession, "before_flush")
def _fence_flush(session, _context, _instances):
    if any(_requires_writer(session, obj)
           for obj in session.new | session.dirty | session.deleted):
        _fence_write(session)


@event.listens_for(_FencedSyncSession, "do_orm_execute")
def _fence_statement(state):
    # Covers projection bulk DELETE/UPDATE as well as ORM flush writes.
    if not state.is_select:
        _fence_write(state.session)


@event.listens_for(_FencedSyncSession, "before_commit")
def _fence_commit(session):
    # before_commit normally precedes SQLAlchemy's automatic flush. Flush
    # here so the final expiry check follows ALL awaited DML, not just the
    # first order insert. Invalid authority rolls back those writes together.
    session.flush()
    if session.info.get("writer_transaction"):
        _fence_write(session)


@event.listens_for(_FencedSyncSession, "after_transaction_end")
def _clear_transaction_fence(session, transaction):
    if transaction.parent is None:
        session.info.pop("writer_transaction", None)


class LeaseManager:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        bind = session_factory.kw["bind"]
        if bind.dialect.name == "sqlite" and not event.contains(
            bind.sync_engine, "checkout", _install_sqlite_clock
        ):
            event.listen(bind.sync_engine, "checkout", _install_sqlite_clock)
        # Central/native execution guards are synchronous. Read the actual
        # committed row on each guard, never a heartbeat cache. NullPool keeps
        # no connection or old transaction snapshot between calls.
        url = session_factory.kw["bind"].url
        if url.get_backend_name() == "sqlite":
            path = quote(str(Path(url.database).resolve()), safe="/")
            url = url.set(drivername="sqlite", database=f"file:{path}",
                          query={"mode": "ro", "uri": "true"})
            self._authority_reader = create_engine(
                # Bounded lock wait, not a grace period: expiry is checked
                # AFTER the query, and unavailable evidence still fails closed.
                url, poolclass=NullPool, connect_args={"timeout": 0.05},
            )
        else:
            self._authority_reader = create_engine(
                url.set(drivername="postgresql+psycopg2"), poolclass=NullPool,
                connect_args={
                    "connect_timeout": 1,
                    "options": "-c statement_timeout=1000 -c default_transaction_read_only=on",
                },
            )
        self.last_authority_error = None

    def fenced_sessions(self, lease_provider, lease_valid, run_id_provider, lease_failed):
        """Actor-bound sessions; standalone tools/tests keep their own factory."""
        return async_sessionmaker(
            class_=_FencedSession, **self.session_factory.kw,
            lease_provider=lease_provider, lease_valid=lease_valid,
            run_id_provider=run_id_provider, lease_failed=lease_failed,
        )

    def is_current_now(self, lease: Lease) -> bool:
        """Fresh fail-closed authority at synchronous execution boundaries."""
        try:
            with self._authority_reader.connect() as connection:
                row = connection.execute(select(
                    RuntimeLeaseORM.expires_at,
                ).where(
                    RuntimeLeaseORM.lease_key == lease.lease_key,
                    RuntimeLeaseORM.owner_id == lease.owner_id,
                    RuntimeLeaseORM.token == lease.token,
                    RuntimeLeaseORM.fence_generation == lease.fence_generation,
                )).one_or_none()
                self.last_authority_error = None
                return row is not None and row.expires_at > _epoch()
        except Exception as exc:
            # Unknown is not historical authority. Never log tokens/URLs.
            error = getattr(exc, "orig", exc)
            self.last_authority_error = {
                "type": type(error).__name__,
                "database_error": getattr(error, "sqlite_errorname", None),
            }
            return False

    async def acquire(self, lease_key: str, owner_id: str, ttl_seconds: float) -> Lease | None:
        token = new_id("lease")
        async with self.session_factory() as session:
            sql_now = _db_epoch(session)
            row = (
                await session.execute(
                    select(RuntimeLeaseORM).where(RuntimeLeaseORM.lease_key == lease_key)
                )
            ).scalar_one_or_none()
            if row is not None and row.expires_at > _epoch():
                if row.owner_id == owner_id and row.token:
                    # CAS the ACTIVE grant; a stale read must not extend or
                    # borrow another owner's grant after an intervening await.
                    result = await session.execute(update(RuntimeLeaseORM).where(
                        RuntimeLeaseORM.id == row.id,
                        RuntimeLeaseORM.owner_id == owner_id,
                        RuntimeLeaseORM.token == row.token,
                        RuntimeLeaseORM.fence_generation == row.fence_generation,
                        RuntimeLeaseORM.expires_at > sql_now,
                    ).values(expires_at=sql_now + ttl_seconds, renewed_at=sql_now,
                             version=RuntimeLeaseORM.version + 1))
                    await session.commit()
                    if result.rowcount != 1:
                        return None
                    await session.refresh(row)
                    return Lease(
                        lease_key,
                        owner_id,
                        row.token,
                        row.expires_at,
                        row.fence_generation,
                    )
                return None
            if row is None:
                row = RuntimeLeaseORM(
                        lease_key=lease_key,
                        owner_id=owner_id,
                        token=token,
                        expires_at=sql_now + ttl_seconds,
                        acquired_at=sql_now,
                        version=1,
                    )
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    return await self.acquire(lease_key, owner_id, ttl_seconds)
                await session.refresh(row)
                return Lease(lease_key, owner_id, token, row.expires_at)
            # expired: atomic CAS
            result = await session.execute(
                update(RuntimeLeaseORM)
                .where(
                    RuntimeLeaseORM.lease_key == lease_key,
                    RuntimeLeaseORM.expires_at <= sql_now,
                )
                .values(
                    owner_id=owner_id,
                    token=token,
                    expires_at=sql_now + ttl_seconds,
                    acquired_at=sql_now,
                    renewed_at=None,
                    version=RuntimeLeaseORM.version + 1,
                    fence_generation=RuntimeLeaseORM.fence_generation + 1,
                )
            )
            await session.commit()
            if result.rowcount == 1:
                await session.refresh(row)
                return Lease(
                    lease_key,
                    owner_id,
                    token,
                    row.expires_at,
                    row.fence_generation,
                )
        return None

    async def renew(
        self,
        lease_key: str,
        token: str,
        ttl_seconds: float,
        *,
        owner_id: str | None = None,
        fence_generation: int | None = None,
    ) -> bool:
        async with self.session_factory() as session:
            sql_now = _db_epoch(session)
            # Strict renewal first: only an ACTIVE lease owned by us.
            statement = update(RuntimeLeaseORM).where(
                RuntimeLeaseORM.lease_key == lease_key,
                RuntimeLeaseORM.token == token,
                RuntimeLeaseORM.expires_at > sql_now,
            )
            if owner_id is not None:
                statement = statement.where(RuntimeLeaseORM.owner_id == owner_id)
            if fence_generation is not None:
                statement = statement.where(
                    RuntimeLeaseORM.fence_generation == int(fence_generation)
                )
            result = await session.execute(
                statement
                .values(expires_at=sql_now + ttl_seconds, renewed_at=sql_now,
                        version=RuntimeLeaseORM.version + 1)
            )
            matched = result.rowcount
            # Expiry ends this authority, even if owner/token still match.
            # Recovery requires acquire() with a new token/fence and startup
            # safety revalidation; renewal must never resurrect the old grant.
            await session.commit()
            return matched == 1

    async def release(
        self,
        lease_key: str,
        token: str,
        *,
        owner_id: str | None = None,
        fence_generation: int | None = None,
    ) -> bool:
        async with self.session_factory() as session:
            statement = update(RuntimeLeaseORM).where(
                RuntimeLeaseORM.lease_key == lease_key,
                RuntimeLeaseORM.token == token,
            )
            if owner_id is not None:
                statement = statement.where(RuntimeLeaseORM.owner_id == owner_id)
            if fence_generation is not None:
                statement = statement.where(
                    RuntimeLeaseORM.fence_generation == int(fence_generation)
                )
            # Preserve the row as a fencing tombstone.  The next acquisition
            # must CAS this expired generation forward instead of recreating
            # generation 1, so a controlled restart is visibly newer.
            result = await session.execute(
                statement.values(
                    expires_at=0.0,
                    renewed_at=_epoch(),
                    version=RuntimeLeaseORM.version + 1,
                )
            )
            matched = result.rowcount
            await session.commit()
            return matched == 1

    async def is_held(self, lease_key: str, token: str | None = None) -> bool:
        if token is None:
            return False
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(RuntimeLeaseORM).where(
                        RuntimeLeaseORM.lease_key == lease_key, RuntimeLeaseORM.token == token
                    )
                )
            ).scalar_one_or_none()
            return row is not None and row.expires_at > _epoch()

    async def is_current(
        self,
        lease_key: str,
        token: str,
        fence_generation: int,
        *,
        owner_id: str | None = None,
    ) -> bool:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(RuntimeLeaseORM).where(
                        RuntimeLeaseORM.lease_key == lease_key,
                        RuntimeLeaseORM.token == token,
                    )
                )
            ).scalar_one_or_none()
            current = (
                row is not None
                and row.expires_at > _epoch()
                and row.fence_generation == int(fence_generation)
            )
            return current and (owner_id is None or row.owner_id == owner_id)

    async def status(self, lease_key: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(RuntimeLeaseORM).where(RuntimeLeaseORM.lease_key == lease_key)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "lease_key": row.lease_key,
                "owner_id": row.owner_id,
                "token": row.token,
                "expires_at": row.expires_at,
                "expired": row.expires_at <= time.time(),
                "version": row.version,
                "fence_generation": row.fence_generation,
            }
