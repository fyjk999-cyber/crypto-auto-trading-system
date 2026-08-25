"""Factor service: persist and query factor snapshots."""

from __future__ import annotations

from sqlalchemy import select

from crypto_trader.factors.models import FactorResult, FactorSnapshot
from crypto_trader.persistence.models import (
    FactorRegistryORM,
    FactorSnapshotORM,
    FactorValueORM,
)


class FactorService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def save_results(self, results: list[FactorResult]) -> None:
        async with self.session_factory() as session:
            for r in results:
                session.add(
                    FactorValueORM(
                        symbol=r.symbol,
                        factor=r.factor_name,
                        timeframe=r.timeframe,
                        value=r.value,
                        confidence=r.confidence,
                        metadata_json=r.metadata,
                    )
                )
            await session.commit()

    async def save_snapshot(self, snapshot: FactorSnapshot) -> None:
        async with self.session_factory() as session:
            session.add(
                FactorSnapshotORM(
                    symbol=snapshot.symbol,
                    timeframe=snapshot.timeframe,
                    snapshot_json=snapshot.to_dict(),
                )
            )
            await session.commit()

    async def latest_snapshot(self, symbol: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(FactorSnapshotORM)
                    .where(FactorSnapshotORM.symbol == symbol)
                    .order_by(FactorSnapshotORM.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row.snapshot_json if row else None

    async def history(self, symbol: str, factor: str, limit: int = 100) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(FactorValueORM)
                        .where(FactorValueORM.symbol == symbol, FactorValueORM.factor == factor)
                        .order_by(FactorValueORM.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                {
                    "factor": r.factor,
                    "symbol": r.symbol,
                    "timeframe": r.timeframe,
                    "value": str(r.value),
                    "confidence": str(r.confidence),
                    "timestamp": r.created_at.isoformat(),
                }
                for r in rows
            ]

    async def ensure_registry(self) -> None:
        from crypto_trader.factors.registry import FactorRegistry

        registry = FactorRegistry()
        async with self.session_factory() as session:
            for item in registry.list():
                row = await session.get(FactorRegistryORM, item["factor_id"])
                if row is None:
                    session.add(
                        FactorRegistryORM(
                            factor_id=item["factor_id"],
                            name=item["name"],
                            version=item["version"],
                            status=item["status"],
                            description=item["description"],
                        )
                    )
            await session.commit()
