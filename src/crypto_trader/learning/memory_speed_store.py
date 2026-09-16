# Persistent store for Growth memory-speed records (derived; LEARNING_ONLY).
from __future__ import annotations

from sqlalchemy import select

from crypto_trader.learning.memory_speeds import (
    POLICY_VERSION,
    MemoryRecord,
    promotion_summary,
)
from crypto_trader.persistence.models import GrowthMemorySpeedORM


class MemorySpeedStore:
    authority = "LEARNING_ONLY"
    can_modify_core = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def save(self, record: MemoryRecord) -> dict:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthMemorySpeedORM).where(GrowthMemorySpeedORM.key == record.key)
                )
            ).scalar_one_or_none()
            if row is None:
                row = GrowthMemorySpeedORM(key=record.key)
                session.add(row)
            row.signature = record.signature
            row.speed = record.speed
            row.observations = record.observations
            row.wins = record.wins
            row.net_bps_total = record.net_bps_total
            row.regimes_json = list(record.regimes)
            row.demotions = record.demotions
            row.post_cost_expectancy_bps = record.post_cost_expectancy_bps
            row.chronological_stable = record.chronological_stable
            row.unresolved_contradictions = record.unresolved_contradictions
            row.policy_version = POLICY_VERSION
            row.can_modify_core = False
            row.authority = "LEARNING_ONLY"
            await session.commit()
        return promotion_summary(record)

    @staticmethod
    def _to_record(row: GrowthMemorySpeedORM) -> MemoryRecord:
        return MemoryRecord(
            key=row.key,
            signature=row.signature,
            speed=row.speed,
            observations=row.observations,
            wins=row.wins,
            net_bps_total=row.net_bps_total,
            regimes=list(row.regimes_json or []),
            demotions=row.demotions,
            post_cost_expectancy_bps=row.post_cost_expectancy_bps,
            chronological_stable=row.chronological_stable,
            unresolved_contradictions=row.unresolved_contradictions,
            authority="LEARNING_ONLY",
            is_order=False,
            can_modify_core=False,
        )

    async def load(self, key: str) -> MemoryRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthMemorySpeedORM).where(GrowthMemorySpeedORM.key == key)
                )
            ).scalar_one_or_none()
        return self._to_record(row) if row is not None else None

    async def load_all(self, limit: int = 500) -> list[MemoryRecord]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GrowthMemorySpeedORM)
                        .order_by(GrowthMemorySpeedORM.observations.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [self._to_record(row) for row in rows]
