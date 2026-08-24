"""DB persistence for Trade Memory and Daily Review runs."""

from __future__ import annotations

from sqlalchemy import select

from crypto_trader.governance.memory import TradeMemoryRecord
from crypto_trader.persistence.models import DailyReviewRunORM, TradeMemoryRecordORM


class MemoryPersistence:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def save_trade_memory(self, record: TradeMemoryRecord) -> None:
        async with self.session_factory() as session:
            row = TradeMemoryRecordORM(
                decision_id=record.decision_id,
                symbol=record.symbol,
                side=record.side,
                regime=record.regime,
                raw_confidence=record.raw_confidence,
                calibrated_confidence=record.calibrated_confidence,
                recommended_position=record.recommended_position,
                approved_position=record.approved_position,
                recommended_leverage=record.recommended_leverage,
                approved_leverage=record.approved_leverage,
                entry=record.entry,
                exit=record.exit,
                mae=record.mae,
                mfe=record.mfe,
                fees=record.fees,
                funding_pnl=record.funding_pnl,
                realized_pnl=record.realized_pnl,
                r_multiple=record.r_multiple,
                failure_class=record.failure_class.value if record.failure_class else None,
                timestamp=record.ts,
            )
            session.add(row)
            await session.commit()

    async def load_trade_memory(self, limit: int = 200) -> list[TradeMemoryRecord]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(TradeMemoryRecordORM)
                        .order_by(TradeMemoryRecordORM.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [_row_to_record(r) for r in rows]

    async def save_daily_review(self, date: str, stats) -> None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == date)
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.daily_pnl = stats.daily_pnl
                existing.long_pnl = stats.long_pnl
                existing.short_pnl = stats.short_pnl
                existing.trade_count = stats.trade_count
                existing.win_rate = stats.win_rate
                existing.profit_factor = stats.profit_factor
                existing.expectancy = stats.expectancy
            else:
                session.add(
                    DailyReviewRunORM(
                        review_date=date,
                        daily_pnl=stats.daily_pnl,
                        long_pnl=stats.long_pnl,
                        short_pnl=stats.short_pnl,
                        trade_count=stats.trade_count,
                        win_rate=stats.win_rate,
                        profit_factor=stats.profit_factor,
                        expectancy=stats.expectancy,
                    )
                )
            await session.commit()

    async def load_daily_reviews(self, limit: int = 60) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(DailyReviewRunORM).order_by(DailyReviewRunORM.id.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                {
                    "date": r.review_date,
                    "daily_pnl": str(r.daily_pnl),
                    "long_pnl": str(r.long_pnl),
                    "short_pnl": str(r.short_pnl),
                    "trade_count": r.trade_count,
                    "win_rate": str(r.win_rate),
                    "profit_factor": str(r.profit_factor),
                    "expectancy": str(r.expectancy),
                }
                for r in rows
            ]


def _row_to_record(r: TradeMemoryRecordORM) -> TradeMemoryRecord:
    from crypto_trader.governance.memory import FailureClass

    return TradeMemoryRecord(
        decision_id=r.decision_id,
        symbol=r.symbol,
        side=r.side,
        regime=r.regime,
        strategy_scores={},
        effective_weights={},
        raw_confidence=r.raw_confidence,
        calibrated_confidence=r.calibrated_confidence,
        recommended_position=r.recommended_position,
        approved_position=r.approved_position,
        recommended_leverage=r.recommended_leverage,
        approved_leverage=r.approved_leverage,
        entry=r.entry,
        exit=r.exit,
        mae=r.mae,
        mfe=r.mfe,
        fees=r.fees,
        funding_pnl=r.funding_pnl,
        realized_pnl=r.realized_pnl,
        r_multiple=r.r_multiple,
        failure_class=FailureClass(r.failure_class) if r.failure_class else None,
        ts=r.timestamp,
    )
