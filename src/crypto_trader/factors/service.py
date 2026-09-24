"""Factor service: persist and query factor snapshots."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from crypto_trader.factors.models import FactorResult, FactorSnapshot
from crypto_trader.persistence.models import (
    FactorAttributionORM,
    FactorCatalogORM,
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

    async def latest_snapshot(self, symbol: str, *, as_of=None) -> dict | None:
        async with self.session_factory() as session:
            stmt = select(FactorSnapshotORM).where(FactorSnapshotORM.symbol == symbol)
            if as_of is not None:
                stmt = stmt.where(FactorSnapshotORM.created_at <= as_of)
            row = (
                await session.execute(stmt.order_by(FactorSnapshotORM.id.desc()).limit(1))
            ).scalar_one_or_none()
            return row.snapshot_json if row else None

    async def history(
        self, symbol: str, factor: str, limit: int = 100, *, as_of=None
    ) -> list[dict]:
        async with self.session_factory() as session:
            stmt = select(FactorValueORM).where(
                FactorValueORM.symbol == symbol, FactorValueORM.factor == factor
            )
            if as_of is not None:
                stmt = stmt.where(FactorValueORM.created_at <= as_of)
            rows = (
                (await session.execute(stmt.order_by(FactorValueORM.id.desc()).limit(limit)))
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


    async def persist_scan_observations(self, observations_by_symbol: dict, observed_at) -> int:
        """Persist factual scanner observations (realtime factor evidence)."""
        from crypto_trader.persistence.models import (
            FactorSnapshotORM,
            FactorValueORM,
        )

        written = 0
        async with self.session_factory() as session:
            for symbol, observations in (observations_by_symbol or {}).items():
                obs_list = list(observations or [])
                if not obs_list:
                    continue
                session.add(
                    FactorSnapshotORM(
                        symbol=str(symbol),
                        timeframe="scan",
                        snapshot_json={
                            "symbol": str(symbol),
                            "timeframe": "scan",
                            "timestamp": observed_at.isoformat(),
                            "observations": [o.as_dict() for o in obs_list],
                        },
                    )
                )
                for obs in obs_list:
                    strength = getattr(obs, "strength", None)
                    value = Decimal(str(strength)) if strength is not None else Decimal("0")
                    status = str(getattr(obs, "status", ""))
                    session.add(
                        FactorValueORM(
                            symbol=str(symbol),
                            factor=str(getattr(obs, "factor", "UNKNOWN")),
                            timeframe="scan",
                            value=value,
                            confidence=Decimal("1") if status == "TRIGGERED" else Decimal("0"),
                            metadata_json=obs.as_dict()
                            if hasattr(obs, "as_dict")
                            else {"status": status},
                        )
                    )
                    written += 1
            await session.commit()
        return written

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

    async def latest_performance(
        self, factor_name: str, symbol: str, *, as_of=None
    ) -> dict | None:
        async with self.session_factory() as session:
            stmt = select(FactorPerformanceORM).where(
                FactorPerformanceORM.factor_name == factor_name,
                FactorPerformanceORM.symbol == symbol,
            )
            if as_of is not None:
                stmt = stmt.where(FactorPerformanceORM.created_at <= as_of)
            row = (
                await session.execute(stmt.order_by(FactorPerformanceORM.id.desc()).limit(1))
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

    async def attribution_for_trade(self, trade_id: str, *, as_of=None) -> list[dict]:
        async with self.session_factory() as session:
            stmt = select(FactorAttributionORM).where(FactorAttributionORM.trade_id == trade_id)
            if as_of is not None:
                stmt = stmt.where(FactorAttributionORM.created_at <= as_of)
            rows = (await session.execute(stmt)).scalars().all()
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

    async def latest_decay(
        self, factor_name: str, symbol: str, *, as_of=None
    ) -> dict | None:
        async with self.session_factory() as session:
            stmt = select(FactorDecayORM).where(
                FactorDecayORM.factor_name == factor_name, FactorDecayORM.symbol == symbol
            )
            if as_of is not None:
                stmt = stmt.where(FactorDecayORM.created_at <= as_of)
            row = (
                await session.execute(stmt.order_by(FactorDecayORM.id.desc()).limit(1))
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

    async def sync_catalog(self) -> None:
        from crypto_trader.factors.catalog import FactorCatalog

        catalog = FactorCatalog()
        async with self.session_factory() as session:
            for item in catalog.list():
                row = await session.get(FactorCatalogORM, item["factor_id"])
                if row is None:
                    session.add(
                        FactorCatalogORM(
                            factor_id=item["factor_id"],
                            name=item["name"],
                            category=item["category"],
                            formula=item["formula"],
                            data_source=item["data_source"],
                            timeframe=item["timeframe"],
                            status=item["status"],
                        )
                    )
                else:
                    row.status = item["status"]
            await session.commit()
