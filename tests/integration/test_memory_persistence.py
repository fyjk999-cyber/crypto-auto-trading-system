from decimal import Decimal

from crypto_trader.governance.memory import FailureClass, TradeMemoryRecord
from crypto_trader.governance.memory_persistence import MemoryPersistence


def make_record(decision_id, pnl):
    return TradeMemoryRecord(
        decision_id=decision_id,
        symbol="BTCUSDT",
        side="LONG",
        regime="BULL",
        strategy_scores={},
        effective_weights={},
        raw_confidence=Decimal("0.8"),
        calibrated_confidence=Decimal("0.7"),
        recommended_position=Decimal("1"),
        approved_position=Decimal("1"),
        recommended_leverage=Decimal("5"),
        approved_leverage=Decimal("3"),
        entry=Decimal("100"),
        exit=Decimal("105"),
        fees=Decimal("0.1"),
        funding_pnl=Decimal("0"),
        realized_pnl=Decimal(pnl),
        r_multiple=Decimal("0.96"),
        failure_class=FailureClass.TIMING_ERROR if Decimal(pnl) < 0 else None,
    )


async def test_trade_memory_persistence_roundtrip(database):
    persistence = MemoryPersistence(database.session_factory)
    await persistence.save_trade_memory(make_record("d1", "4.8"))
    rows = await persistence.load_trade_memory(limit=10)
    assert len(rows) == 1
    assert rows[0].decision_id == "d1"
    assert rows[0].realized_pnl == Decimal("4.8")


async def test_daily_review_persistence_is_idempotent(database):
    persistence = MemoryPersistence(database.session_factory)
    from crypto_trader.governance.daily_review import DailyReviewStats

    stats = DailyReviewStats(
        date="2026-08-24",
        daily_pnl=Decimal("10"),
        long_pnl=Decimal("10"),
        trade_count=2,
        win_rate=Decimal("0.5"),
    )
    await persistence.save_daily_review("2026-08-24", stats)
    await persistence.save_daily_review("2026-08-24", stats)
    rows = await persistence.load_daily_reviews(limit=10)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-08-24"
    assert rows[0]["daily_pnl"] == "10"
