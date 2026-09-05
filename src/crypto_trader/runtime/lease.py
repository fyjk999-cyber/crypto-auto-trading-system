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

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import RuntimeLeaseORM


def _epoch(dt: datetime | None = None) -> float:
    return (dt or datetime.now(UTC)).timestamp()


@dataclass
class Lease:
    lease_key: str
    owner_id: str
    token: str
    expires_at: float
    fence_generation: int = 1


class LeaseManager:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def acquire(self, lease_key: str, owner_id: str, ttl_seconds: float) -> Lease | None:
        now = _epoch()
        expires_at = now + ttl_seconds
        token = new_id("lease")
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(RuntimeLeaseORM).where(RuntimeLeaseORM.lease_key == lease_key)
                )
            ).scalar_one_or_none()
            if row is not None and row.expires_at > now:
                if row.owner_id == owner_id and row.token:
                    # same writer renews/extend its own active lease
                    row.expires_at = expires_at
                    row.renewed_at = now
                    row.version += 1
                    await session.commit()
                    return Lease(
                        lease_key,
                        owner_id,
                        row.token,
                        expires_at,
                        row.fence_generation,
                    )
                return None
            if row is None:
                session.add(
                    RuntimeLeaseORM(
                        lease_key=lease_key,
                        owner_id=owner_id,
                        token=token,
                        expires_at=expires_at,
                        acquired_at=now,
                        version=1,
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    return await self.acquire(lease_key, owner_id, ttl_seconds)
                return Lease(lease_key, owner_id, token, expires_at)
            # expired: atomic CAS
            result = await session.execute(
                update(RuntimeLeaseORM)
                .where(
                    RuntimeLeaseORM.lease_key == lease_key,
                    RuntimeLeaseORM.expires_at <= now,
                )
                .values(
                    owner_id=owner_id,
                    token=token,
                    expires_at=expires_at,
                    acquired_at=now,
                    renewed_at=None,
                    version=RuntimeLeaseORM.version + 1,
                    fence_generation=RuntimeLeaseORM.fence_generation + 1,
                )
            )
            await session.commit()
            if result.rowcount == 1:
                refreshed = await session.get(RuntimeLeaseORM, row.id)
                return Lease(
                    lease_key,
                    owner_id,
                    token,
                    expires_at,
                    refreshed.fence_generation if refreshed else row.fence_generation + 1,
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
        now = _epoch()
        expires_at = now + ttl_seconds
        async with self.session_factory() as session:
            statement = update(RuntimeLeaseORM).where(
                RuntimeLeaseORM.lease_key == lease_key,
                RuntimeLeaseORM.token == token,
                RuntimeLeaseORM.expires_at > now,
            )
            if owner_id is not None:
                statement = statement.where(RuntimeLeaseORM.owner_id == owner_id)
            if fence_generation is not None:
                statement = statement.where(
                    RuntimeLeaseORM.fence_generation == int(fence_generation)
                )
            result = await session.execute(
                statement
                .values(expires_at=expires_at, renewed_at=now, version=RuntimeLeaseORM.version + 1)
            )
            await session.commit()
            return result.rowcount == 1

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
            await session.commit()
            return result.rowcount == 1

    async def is_held(self, lease_key: str, token: str | None = None) -> bool:
        if token is None:
            return False
        now = _epoch()
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(RuntimeLeaseORM).where(
                        RuntimeLeaseORM.lease_key == lease_key, RuntimeLeaseORM.token == token
                    )
                )
            ).scalar_one_or_none()
            return row is not None and row.expires_at > now

    async def is_current(
        self,
        lease_key: str,
        token: str,
        fence_generation: int,
        *,
        owner_id: str | None = None,
    ) -> bool:
        now = _epoch()
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
                and row.expires_at > now
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
