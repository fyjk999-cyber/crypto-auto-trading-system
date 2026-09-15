"""Growth V2 write-through persistence (Phase 5).

Persists the seven-taxonomy reviews into the existing ``ai_trade_reviews`` table
and outcome evaluations into the existing ``trade_memory_records`` table — no
parallel Growth database, no second source of truth.

Learning/observability only: these writers never touch orders, Risk or
Execution.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from crypto_trader.persistence.models import AITradeReviewORM, TradeMemoryRecordORM


class GrowthPersistence:
    authority = "LEARNING_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def write_reviews(self, *, trading_day: str, findings: list) -> int:
        written = 0
        async with self._session_factory() as session:
            for finding in findings:
                episode_id = f"{trading_day}:{finding.review_type}:{finding.event_kind}"
                row = (
                    await session.execute(
                        select(AITradeReviewORM).where(AITradeReviewORM.episode_id == episode_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = AITradeReviewORM(episode_id=episode_id)
                    session.add(row)
                lessons = [finding.lesson] if finding.lesson else []
                if finding.verdict == "DEFECT":
                    row.failure_factors_json = list(finding.observations) or ["DEFECT"]
                    row.mistakes_json = [finding.review_type]
                else:
                    row.success_factors_json = [finding.verdict]
                row.lessons_json = lessons
                row.future_rules_json = [f"{finding.review_type}:{finding.verdict}"]
                row.confidence = Decimal("0.5")
                written += 1
            await session.commit()
        return written

    async def write_outcome_memory(
        self,
        *,
        trading_day: str,
        symbol: str,
        side: str,
        regime: str,
        outcomes: list,
    ) -> int:
        written = 0
        async with self._session_factory() as session:
            for outcome in outcomes:
                decision_id = f"{trading_day}:{symbol}:{outcome.horizon}"
                row = (
                    await session.execute(
                        select(TradeMemoryRecordORM).where(
                            TradeMemoryRecordORM.decision_id == decision_id
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = TradeMemoryRecordORM(decision_id=decision_id)
                    session.add(row)
                row.symbol = symbol[:32]
                row.side = side.upper()[:8]
                row.regime = regime[:16]
                row.raw_confidence = Decimal("0.5")
                row.calibrated_confidence = Decimal("0.5")
                row.recommended_position = Decimal("0")
                row.approved_position = Decimal("0")
                row.recommended_leverage = Decimal("0")
                row.approved_leverage = Decimal("0")
                row.mae = Decimal(str(outcome.mae_bps))
                row.mfe = Decimal(str(outcome.mfe_bps))
                row.realized_pnl = Decimal(str(outcome.net_return_bps))
                row.r_multiple = Decimal("0")
                row.failure_class = (
                    outcome.label
                    if outcome.label in {"TRADED_WRONG", "NOT_TRADED_MISSED"}
                    else None
                )
                written += 1
            await session.commit()
        return written

    async def list_reviews(self, *, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AITradeReviewORM).order_by(AITradeReviewORM.id.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "episode_id": row.episode_id,
                "lessons": row.lessons_json or [],
                "future_rules": row.future_rules_json or [],
                "failure_factors": row.failure_factors_json or [],
            }
            for row in rows
        ]
