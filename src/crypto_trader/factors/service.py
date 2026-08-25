"""Factor service: persist and query factor snapshots."""

from __future__ import annotations

from sqlalchemy import select

from crypto_trader.factors.models import FactorResult, FactorSnapshot
from crypto_trader.persistence.models import (
    FactorAttributionORM,
    FactorDecayORM,
    FactorPerformanceORM,
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

    async def save_performance(self, performance) -> None:
        async with self.session_factory() as session:
            session.add(
                FactorPerformanceORM(
                    factor_name=performance.factor_name,
                    symbol=performance.symbol,
                    timeframe=performance.timeframe,
                    sample_size=performance.sample_size,
                    win_rate=performance.win_rate,
                    average_return=performance.average_return,
                    sharpe=performance.sharpe,
                    max_drawdown=performance.max_drawdown,
                    profit_factor=performance.profit_factor,
                )
            )
            await session.commit()

    async def latest_performance(self, factor_name: str, symbol: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(FactorPerformanceORM)
                    .where(
                        FactorPerformanceORM.factor_name == factor_name,
                        FactorPerformanceORM.symbol == symbol,
                    )
                    .order_by(FactorPerformanceORM.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "factor_name": row.factor_name,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "sample_size": row.sample_size,
                "win_rate": str(row.win_rate),
                "average_return": str(row.average_return),
                "sharpe": str(row.sharpe),
                "max_drawdown": str(row.max_drawdown),
                "profit_factor": str(row.profit_factor),
                "timestamp": row.created_at.isoformat(),
            }

    async def save_attribution(self, attribution) -> None:
        async with self.session_factory() as session:
            for name, contribution in attribution.contributors.items():
                session.add(
                    FactorAttributionORM(
                        trade_id=attribution.trade_id,
                        factor_name=name,
                        contribution=contribution,
                        direction="positive",
                    )
                )
            for name, contribution in attribution.negative.items():
                session.add(
                    FactorAttributionORM(
                        trade_id=attribution.trade_id,
                        factor_name=name,
                        contribution=contribution,
                        direction="negative",
                    )
                )
            await session.commit()

    async def attribution_for_trade(self, trade_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(FactorAttributionORM).where(
                            FactorAttributionORM.trade_id == trade_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [
                {
                    "factor_name": r.factor_name,
                    "contribution": str(r.contribution),
                    "direction": r.direction,
                }
                for r in rows
            ]

    async def save_decay(self, decay) -> None:
        async with self.session_factory() as session:
            session.add(
                FactorDecayORM(
                    factor_name=decay.factor_name,
                    symbol=decay.symbol,
                    status=decay.status,
                    old_performance=decay.old_performance,
                    new_performance=decay.new_performance,
                    reason=decay.reason,
                )
            )
            await session.commit()

    async def latest_decay(self, factor_name: str, symbol: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(FactorDecayORM)
                    .where(
                        FactorDecayORM.factor_name == factor_name, FactorDecayORM.symbol == symbol
                    )
                    .order_by(FactorDecayORM.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "factor_name": row.factor_name,
                "symbol": row.symbol,
                "status": row.status,
                "old_performance": str(row.old_performance),
                "new_performance": str(row.new_performance),
                "reason": row.reason,
                "timestamp": row.created_at.isoformat(),
            }
