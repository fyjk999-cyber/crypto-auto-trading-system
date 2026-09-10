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


async def test_daily_review_claim_is_atomic(database):
    import asyncio
    from datetime import UTC, datetime

    persistence = MemoryPersistence(database.session_factory)
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 10, tzinfo=UTC)
    first, second = await asyncio.gather(
        persistence.begin_daily_review("2026-09-09", start, end),
        persistence.begin_daily_review("2026-09-09", start, end),
    )
    tokens = [t for t in (first, second) if t is not None]
    assert len(tokens) == 1


async def test_learning_retry_does_not_bump_pattern_version(database):
    from datetime import UTC, datetime

    from sqlalchemy import select

    from crypto_trader.governance.factual_learning import FactualEpisodeLearning
    from crypto_trader.governance.trade_episode import FactualTradeEpisode
    from crypto_trader.persistence.models import AIMarketPatternORM, TradeEpisodeORM

    episode = FactualTradeEpisode(
        episode_id="ep_retry",
        trade_plan_id="plan_retry",
        symbol="BTCUSDT",
        direction="LONG",
        entry_decision_id="d1",
        exit_decision_id="d2",
        position_decision_ids=[],
        risk_decision_ids=[],
        order_ids=[],
        fill_ids=[],
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        holding_time_seconds=1.0,
        entry_market_regime="TREND",
        terminal_reason="EXIT",
        opened_at=datetime(2026, 9, 9, tzinfo=UTC),
        closed_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    async with database.session_factory() as session:
        session.add(
            TradeEpisodeORM(
                episode_id="ep_retry",
                trade_plan_id="plan_retry",
                symbol="BTCUSDT",
                direction="LONG",
                entry_decision_id="d1",
                entry_price=Decimal("100"),
                exit_price=Decimal("101"),
                opened_quantity=Decimal("1"),
                closed_quantity=Decimal("1"),
                leverage=Decimal("1"),
                gross_pnl=Decimal("1"),
                net_pnl=Decimal("1"),
                holding_time_seconds=1.0,
                entry_market_regime="TREND",
                terminal_reason="EXIT",
                factual=True,
                opened_at=datetime(2026, 9, 9, tzinfo=UTC),
                closed_at=datetime(2026, 9, 9, tzinfo=UTC),
            )
        )
        await session.commit()

    learning = FactualEpisodeLearning(database.session_factory)
    await learning.review(episode)
    await learning.review(episode)
    async with database.session_factory() as session:
        pattern = (await session.execute(select(AIMarketPatternORM))).scalar_one()
    assert pattern.version == 1
    assert pattern.sample_count == 1
