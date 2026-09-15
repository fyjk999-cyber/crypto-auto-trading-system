"""Phase 5: Growth write-through into existing review/memory tables."""

from __future__ import annotations

from crypto_trader.learning.growth_persistence import GrowthPersistence
from crypto_trader.learning.review_taxonomy import classify_review
from crypto_trader.market_data.opportunity.outcomes import evaluate_opportunity


async def test_write_through_uses_existing_tables(database) -> None:
    writer = GrowthPersistence(database.session_factory)
    findings = [
        classify_review(event_kind="ADD", outcome_bps=5.0),
        classify_review(event_kind="HEDGE", outcome_bps=-3.0),
        classify_review(event_kind="RISK_L2"),
    ]
    assert await writer.write_reviews(
        trading_day="2026-09-16", findings=[f for f in findings if f is not None]
    ) == 3

    reviews = await writer.list_reviews(limit=10)
    assert len(reviews) == 3
    defect = [row for row in reviews if row["failure_factors"]]
    assert defect and defect[0]["failure_factors"] == ["outcome_bps=-3.0"]

    outcomes = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=True,
        window_prices={"1h": 101.0, "4h": 99.0},
    )
    assert (
        await writer.write_outcome_memory(
            trading_day="2026-09-16",
            symbol="BTCUSDT",
            side="LONG",
            regime="TREND_UP",
            outcomes=outcomes,
        )
        == 2
    )

    # Idempotent: re-writing updates, never duplicates.
    await writer.write_outcome_memory(
        trading_day="2026-09-16",
        symbol="BTCUSDT",
        side="LONG",
        regime="TREND_UP",
        outcomes=outcomes,
    )
    from sqlalchemy import select

    from crypto_trader.persistence.models import TradeMemoryRecordORM

    async with database.session_factory() as session:
        rows = (
            (await session.execute(select(TradeMemoryRecordORM))).scalars().all()
        )
    assert len(rows) == 2
    assert {row.decision_id for row in rows} == {
        "2026-09-16:BTCUSDT:1h",
        "2026-09-16:BTCUSDT:4h",
    }
    assert writer.authority == "LEARNING_ONLY"
    assert writer.is_order is False
