"""DB persistence for Trade Memory and Daily Review runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update

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

    async def begin_daily_review(
        self, date: str, window_start: datetime, window_end: datetime
    ) -> str | None:
        """Atomically claim a review date; returns claim token or None."""
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=30)
        token = uuid4().hex

        def claim_values() -> dict:
            return {
                "status": "RUNNING",
                "claim_token": token,
                "started_at": now,
                "last_attempt_at": now,
                "last_error_type": None,
                "last_error_detail_sanitized": None,
            }

        async with self.session_factory() as session:
            result = await session.execute(
                update(DailyReviewRunORM)
                .where(
                    DailyReviewRunORM.review_date == date,
                    DailyReviewRunORM.status != "SUCCEEDED",
                    or_(
                        DailyReviewRunORM.status != "RUNNING",
                        DailyReviewRunORM.last_attempt_at < stale_before,
                        DailyReviewRunORM.last_attempt_at.is_(None),
                    ),
                )
                .values(
                    **claim_values(),
                    attempt_count=DailyReviewRunORM.attempt_count + 1,
                )
            )
            if result.rowcount == 1:
                await session.commit()
                return token

            existing = (
                await session.execute(
                    select(DailyReviewRunORM).where(
                        DailyReviewRunORM.review_date == date
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                await session.commit()
                return None

            try:
                session.add(
                    DailyReviewRunORM(
                        review_date=date,
                        window_start_utc=window_start,
                        window_end_utc=window_end,
                        attempt_count=1,
                        **claim_values(),
                    )
                )
                await session.commit()
                return token
            except Exception:
                await session.rollback()
                return None

    async def fail_daily_review(
        self, date: str, error_type: str, detail: str, *, claim_token: str | None = None
    ) -> None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == date)
                )
            ).scalar_one_or_none()
            if existing is None:
                return
            if claim_token is not None and existing.claim_token != claim_token:
                return
            existing.status = "FAILED"
            existing.last_error_type = error_type[:64]
            existing.last_error_detail_sanitized = detail[:255]
            existing.last_attempt_at = datetime.now(UTC)
            await session.commit()

    async def save_daily_review(
        self,
        date: str,
        stats,
        *,
        episode_count: int = 0,
        output_ref: str | None = None,
        claim_token: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == date)
                )
            ).scalar_one_or_none()
            if existing is not None:
                if claim_token is not None and existing.claim_token != claim_token:
                    return
                existing.daily_pnl = stats.daily_pnl
                existing.long_pnl = stats.long_pnl
                existing.short_pnl = stats.short_pnl
                existing.trade_count = stats.trade_count
                existing.win_rate = stats.win_rate
                existing.profit_factor = stats.profit_factor
                existing.expectancy = stats.expectancy
                existing.episode_count = episode_count
                existing.output_ref = output_ref
                existing.status = "SUCCEEDED"
                existing.completed_at = datetime.now(UTC)
                existing.last_attempt_at = datetime.now(UTC)
            else:
                session.add(
                    DailyReviewRunORM(
                        review_date=date,
                        status="SUCCEEDED",
                        attempt_count=1,
                        started_at=datetime.now(UTC),
                        completed_at=datetime.now(UTC),
                        last_attempt_at=datetime.now(UTC),
                        episode_count=episode_count,
                        output_ref=output_ref,
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




    async def latest_succeeded_review_date(self) -> str | None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(DailyReviewRunORM)
                    .where(DailyReviewRunORM.status == "SUCCEEDED")
                    .order_by(DailyReviewRunORM.review_date.desc())
                    .limit(1)
                )
            ).scalars().all()
        return rows[0].review_date if rows else None

    async def get_daily_review(self, date: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == date)
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "date": row.review_date,
            "status": row.status,
            "daily_pnl": str(row.daily_pnl),
            "long_pnl": str(row.long_pnl),
            "short_pnl": str(row.short_pnl),
            "trade_count": row.trade_count,
            "win_rate": str(row.win_rate),
            "profit_factor": str(row.profit_factor),
            "expectancy": str(row.expectancy),
            "episode_count": row.episode_count,
            "attempt_count": row.attempt_count,
        }

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
