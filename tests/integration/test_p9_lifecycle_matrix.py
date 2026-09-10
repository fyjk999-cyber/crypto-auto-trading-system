"""P9: full lifecycle + duplicate-fill/restart engineering invariants."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.domain.enums import LedgerEntryType
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import (
    LedgerEntryORM,
    TradeEpisodeORM,
)
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.strategy.test_strategy import TestStrategy
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import (
    BTC_EXECUTION_METADATA,
    Evidence,
    MutableClock,
    SequencedChief,
)


async def _settled_ledger_entry_count(database, fill_id: str) -> int:
    async with database.session_factory() as session:
        rows = (
            await session.execute(
                select(LedgerEntryORM).where(LedgerEntryORM.fill_id == fill_id)
            )
        ).scalars().all()
    return len(rows)


@pytest.mark.parametrize(
    ("direction", "side", "stop_loss", "limit_price"),
    [("LONG", "BUY", 95, 101), ("SHORT", "SELL", 105, 99)],
)
async def test_full_lifecycle_is_symmetric_and_creates_one_episode(
    database, direction, side, stop_loss, limit_price
):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start(f"run-p9-{direction.lower()}")
    assert await engine._strategy_context("BTCUSDT") is not None

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id=f"entry-{direction.lower()}",
        symbol="BTCUSDT",
        action=direction,
        market_regime="TREND",
        thesis=f"original {direction.lower()} thesis",
        position_size_request=0.1,
        leverage_request=10,
        stop_loss=stop_loss,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="p9-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry,
        limit_price=Decimal(str(limit_price)),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    decision = await engine.process_signal(signal)
    assert decision is not None
    assert decision.side.value == side
    await engine.wait_for_event_queue()
    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is not None
    expected_sign = 1 if direction == "LONG" else -1
    assert position.quantity == Decimal("0.1") * expected_sign

    chief = SequencedChief([("HOLD", "0"), ("REDUCE", "0.04"), ("EXIT", "0")])
    engine.position_manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )

    # HOLD: no order, position stays ACTIVE and unchanged.
    before_orders = len(engine.adapter.orders)
    assert await engine.tick() == []
    assert len(engine.adapter.orders) == before_orders
    active = await plans.get(plan.trade_plan_id)
    assert active is not None and active.state == TradePlanState.ACTIVE

    # REDUCE: partial, reduce-only, never crosses zero or reverses.
    clock.advance()
    reduction = await engine.tick()
    await engine.wait_for_event_queue()
    reduced_position = await engine.portfolio.get_position("BTCUSDT")
    assert reduced_position is not None
    assert reduced_position.quantity == Decimal("0.06") * expected_sign
    assert reduced_position.quantity * expected_sign > 0
    assert reduction[0].checks["original_direction"] == direction
    plan_after_reduce = await plans.get(plan.trade_plan_id)
    assert plan_after_reduce is not None
    assert plan_after_reduce.state == TradePlanState.ACTIVE
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []

    # EXIT: factual zero -> CLOSED -> exactly one episode.
    clock.advance()
    exit_decisions = await engine.tick()
    assert exit_decisions[0].checks["original_direction"] == direction
    await engine.wait_for_event_queue()
    closed_position = await engine.portfolio.get_position("BTCUSDT")
    closed_plan = await plans.get(plan.trade_plan_id)
    assert closed_position is not None and closed_position.quantity == 0
    assert closed_plan is not None and closed_plan.state == TradePlanState.CLOSED
    async with database.session_factory() as session:
        episodes = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(episodes) == 1
    assert episodes[0].direction == direction
    assert episodes[0].closed_quantity == Decimal("0.1")
    assert episodes[0].factual is True

    review = await DailyReviewScheduler(
        database.session_factory, canonical_only=True
    ).run_once(episodes[0].closed_at.date().isoformat())
    assert review["status"] == "SUCCEEDED"
    duplicate = await DailyReviewScheduler(
        database.session_factory, canonical_only=True
    ).run_once(episodes[0].closed_at.date().isoformat())
    assert duplicate.get("idempotent") is True
    await engine.stop()


@pytest.mark.parametrize("fill_before_ack", [False, True])
async def test_duplicate_or_reordered_fill_is_settled_exactly_once(
    database, fill_before_ack
):
    simulator = SimulatedExchangeAdapter(
        initial_balances={"USDT": Decimal("10000")}
    )
    simulator.duplicate_fill = True
    simulator.fill_before_ack = fill_before_ack
    engine = make_paper_engine(
        database,
        strategy=TestStrategy(quantity="0.1", limit_price="101"),
        simulator=simulator,
        engine_tick_seconds=3600,
    )
    await engine.start(f"run-p9-duplicate-{fill_before_ack}")
    await engine.tick()
    await engine.wait_for_event_queue()

    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is not None
    assert position.quantity == Decimal("0.1")
    # Duplicate fill events must not create a second position increase or a
    # second accounting transaction for the same factual fill id.
    order = list(engine.adapter.orders.values())[-1]
    assert order.status.value in {"FILLED", "PARTIALLY_FILLED"}
    async with database.session_factory() as session:
        trade_entries = (
            await session.execute(
                select(LedgerEntryORM).where(
                    LedgerEntryORM.entry_type == LedgerEntryType.TRADE.value
                )
            )
        ).scalars().all()
    transaction_ids = {entry.transaction_id for entry in trade_entries}
    fill_ids = {entry.fill_id for entry in trade_entries}
    assert len(transaction_ids) == 1
    assert len(fill_ids) == 1 and None not in fill_ids
    assert await _settled_ledger_entry_count(database, next(iter(fill_ids))) >= 1
    await engine.stop()
