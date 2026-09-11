"""G01 hand-calculated financial-truth regressions (TEST_ONLY)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.governance.daily_review import (
    NET_STATUS_COMPLETE,
    NET_STATUS_INCOMPLETE,
    PF_STATUS_NO_LOSSES,
    DailyReview,
)
from crypto_trader.governance.memory import TradeMemory, TradeMemoryRecord


def _record(
    decision_id: str,
    *,
    side: str = "LONG",
    realized: str,
    fees: str = "0",
    funding: str = "0",
    funding_provenance: str | None = "PROVEN",
    ts: datetime | None = None,
) -> TradeMemoryRecord:
    record = TradeMemoryRecord(
        decision_id=decision_id,
        symbol="BTCUSDT",
        side=side,
        regime="TREND",
        strategy_scores={},
        effective_weights={},
        raw_confidence=Decimal("0.5"),
        calibrated_confidence=Decimal("0.5"),
        recommended_position=Decimal("1"),
        approved_position=Decimal("1"),
        recommended_leverage=Decimal("1"),
        approved_leverage=Decimal("1"),
        entry=Decimal("100"),
        exit=Decimal("101"),
        fees=Decimal(fees),
        funding_pnl=Decimal(funding),
        realized_pnl=Decimal(realized),
        ts=ts or datetime(2026, 9, 9, 12, tzinfo=UTC),
    )
    if funding_provenance is not None:
        record.funding_provenance = funding_provenance
    return record


def _run(records: list[TradeMemoryRecord], *, policy: str = "STRICT"):
    memory = TradeMemory()
    for record in records:
        memory.record(record)
    return DailyReview(memory, None, funding_policy=policy).run("2026-09-09")


def test_long_and_short_use_net_of_fees_and_funding():
    stats = _run(
        [
            _record("long", side="LONG", realized="10", fees="1", funding="-2"),
            _record("short", side="SHORT", realized="5", fees="0.5", funding="0.5"),
        ]
    )
    assert stats.gross_pnl == Decimal("15")
    assert stats.fees == Decimal("1.5")
    assert stats.funding_pnl == Decimal("-1.5")
    assert stats.net_pnl == Decimal("12")
    assert stats.long_net_pnl == Decimal("7")  # 10 - 1 - 2
    assert stats.short_net_pnl == Decimal("5")  # 5 - 0.5 + 0.5
    assert stats.long_pnl == Decimal("7")
    assert stats.short_pnl == Decimal("5")
    assert stats.net_status == NET_STATUS_COMPLETE


def test_gross_winner_can_be_net_loser():
    stats = _run([_record("gross-win-net-loss", realized="1", fees="0.7", funding="-0.5")])
    assert stats.gross_pnl == Decimal("1")
    assert stats.net_pnl == Decimal("-0.2")
    assert stats.win_count == 0
    assert stats.loss_count == 1
    assert stats.breakeven_count == 0
    assert stats.win_rate == Decimal("0")
    assert stats.expectancy == Decimal("-0.2")


def test_zero_net_trade_is_breakeven_not_a_win_or_loss():
    stats = _run([_record("flat", realized="1", fees="1", funding="0")])
    assert stats.net_pnl == Decimal("0")
    assert stats.win_count == 0
    assert stats.loss_count == 0
    assert stats.breakeven_count == 1
    assert stats.win_rate == Decimal("0")
    # One trade with no losses: ratio is undefined, never 999 and never an amount.
    assert stats.profit_factor is None
    assert stats.profit_factor_status == PF_STATUS_NO_LOSSES
    assert stats.legacy_metrics()["profit_factor"] == Decimal("0")


def test_funding_unknown_does_not_become_zero_or_a_complete_conclusion():
    stats = _run(
        [
            _record("known", realized="2", fees="0", funding="1"),
            _record(
                "unknown-funding",
                realized="2",
                fees="0",
                funding="0",
                funding_provenance="UNKNOWN",
            ),
        ]
    )
    assert stats.trade_count == 2
    assert stats.net_pnl is None
    assert stats.net_status == NET_STATUS_INCOMPLETE
    assert stats.funding_status == "UNKNOWN"
    assert stats.unknown_funding_count == 1
    assert stats.win_rate is None and stats.profit_factor is None and stats.expectancy is None
    assert stats.profit_factor_status == "INCOMPLETE_FUNDING"
    # The stored legacy mirror is explicitly partial, not silently complete.
    assert stats.daily_pnl == Decimal("5")  # 4 gross - 0 fees + 1 known funding
    assert stats.legacy_metrics()["net_status"] == NET_STATUS_INCOMPLETE


def test_no_samples_yields_nullable_ratios_with_status():
    stats = _run([])
    assert stats.trade_count == 0
    assert stats.net_pnl is None
    assert stats.win_rate is None
    assert stats.profit_factor is None
    assert stats.profit_factor_status == "NO_SAMPLES"


def test_account_currency_memories_are_isolated():
    usdt = TradeMemory()
    usdt.record(_record("usdt-1", realized="1", fees="0", funding="0"))
    eur = TradeMemory()
    eur.record(_record("eur-1", realized="999", fees="0", funding="0"))

    usdt_stats = DailyReview(usdt, None, funding_policy="STRICT").run("2026-09-09")
    eur_stats = DailyReview(eur, None, funding_policy="STRICT").run("2026-09-09")
    assert usdt_stats.net_pnl == Decimal("1")
    assert eur_stats.net_pnl == Decimal("999")
    assert usdt_stats.trade_count == 1 and eur_stats.trade_count == 1


def test_compatibility_policy_is_explicit_and_never_used_for_factual_records():
    # Legacy in-memory callers may opt into ASSUME_PRESENT; STRICT is the
    # scheduler path for factual episodes and legacy DB records.
    legacy = TradeMemory()
    legacy.record(_record("legacy", realized="1", fees="0", funding="0", funding_provenance=None))
    assumed = DailyReview(legacy, None, funding_policy="ASSUME_PRESENT").run("2026-09-09")
    strict = DailyReview(legacy, None, funding_policy="STRICT").run("2026-09-09")
    assert assumed.net_status == NET_STATUS_COMPLETE
    assert strict.net_status == NET_STATUS_INCOMPLETE


async def test_scheduler_reports_complete_net_for_factual_episodes(database):
    from datetime import timedelta

    from crypto_trader.governance.scheduler import DailyReviewScheduler
    from crypto_trader.persistence.models import TradeEpisodeORM

    closed = datetime(2026, 9, 9, 12, tzinfo=UTC)
    async with database.session_factory() as session:
        session.add(
            TradeEpisodeORM(
                episode_id="episode_complete",
                trade_plan_id="plan_complete",
                symbol="BTCUSDT",
                direction="LONG",
                entry_decision_id="entry",
                exit_decision_id="exit",
                entry_price=Decimal("100"),
                exit_price=Decimal("102"),
                opened_quantity=Decimal("1"),
                closed_quantity=Decimal("1"),
                leverage=Decimal("1"),
                fees=Decimal("1"),
                funding_pnl=Decimal("-0.5"),
                gross_pnl=Decimal("2"),
                net_pnl=Decimal("0.5"),
                holding_time_seconds=60,
                entry_market_regime="TREND",
                terminal_reason="EXIT",
                factual=True,
                review_status="PENDING",
                opened_at=closed - timedelta(hours=1),
                closed_at=closed,
            )
        )
        await session.commit()
    scheduler = DailyReviewScheduler(database.session_factory, canonical_only=True)
    result = await scheduler.run_once("2026-09-09")
    assert result["status"] == "SUCCEEDED"
    assert result["net_status"] == "COMPLETE"
    assert result["gross_pnl"] == "2"
    assert result["fees"] == "1"
    assert result["funding_pnl"] == "-0.5"
    assert result["net_pnl"] == "0.5"
    assert result["profit_factor"] is None
    assert result["profit_factor_status"] == "NO_LOSSES"


async def test_scheduler_marks_legacy_record_day_incomplete_not_zero(database):
    from crypto_trader.governance.scheduler import DailyReviewScheduler
    from crypto_trader.persistence.models import DailyReviewRunORM, TradeMemoryRecordORM

    closed = datetime(2026, 9, 9, 12, tzinfo=UTC)
    async with database.session_factory() as session:
        session.add(
            TradeMemoryRecordORM(
                decision_id="legacy_decision",
                symbol="BTCUSDT",
                side="LONG",
                regime="TREND",
                raw_confidence=Decimal("0.5"),
                calibrated_confidence=Decimal("0.5"),
                recommended_position=Decimal("1"),
                approved_position=Decimal("1"),
                recommended_leverage=Decimal("1"),
                approved_leverage=Decimal("1"),
                fees=Decimal("0.25"),
                funding_pnl=Decimal("0"),
                realized_pnl=Decimal("2"),
                r_multiple=Decimal("0"),
                timestamp=closed,
            )
        )
        await session.commit()
    scheduler = DailyReviewScheduler(
        database.session_factory, canonical_only=False
    )
    result = await scheduler.run_once("2026-09-09")
    assert result["net_status"] == "INCOMPLETE_UNKNOWN_FUNDING"
    assert result["net_pnl"] is None
    assert result["daily_pnl"] == "1.75"  # explicit partial mirror, not a complete net
    assert result["unknown_funding_count"] == 1
    async with database.session_factory() as session:
        from sqlalchemy import select

        row = (
            await session.execute(
                select(DailyReviewRunORM).where(
                    DailyReviewRunORM.review_date == "2026-09-09"
                )
            )
        ).scalar_one()
    assert "net_status=INCOMPLETE_UNKNOWN_FUNDING" in (row.output_ref or "")
    # Legacy columns still exist but never claim a complete ratio.
    assert row.profit_factor == Decimal("0")
