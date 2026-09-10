from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.domain.clock import Clock
from crypto_trader.domain.enums import ExecutionDecision, OrderStatus
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import (
    AIMarketPatternORM,
    AITradeReviewORM,
    TradeEpisodeORM,
)
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine

BTC_EXECUTION_METADATA = {
    "instrument_type": "LINEAR_PERP",
    "contract_size": "0.01",
    "contract_multiplier": "1",
}


class MutableClock(Clock):
    def __init__(self) -> None:
        self.value = datetime.now(UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int = 31) -> None:
        self.value += timedelta(seconds=seconds)


class Evidence:
    name = "factual_evidence"
    symbol = "BTCUSDT"

    def analyze_evidence(self, ctx):
        return {
            "regime": {"regime": "TREND"},
            "source_refs": [f"orderbook:{ctx.symbol}"],
            "data_quality": "FACTUAL_ORDERBOOK",
        }


class SequencedChief:
    def __init__(self, sequence: list[tuple[str, str]]) -> None:
        self.sequence = sequence
        self.calls = 0

    async def decide(self, ctx):
        action, quantity = self.sequence[self.calls]
        self.calls += 1
        return ChiefTraderDecision(
            decision_id=f"position-{self.calls}-{action.lower()}",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action=action,
            market_regime=ctx.regime,
            thesis=f"factual {action.lower()} decision",
            position_size_request=float(quantity),
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )


async def test_long_hold_reduce_exit_closes_only_after_factual_zero_position(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-long-lifecycle")
    assert await engine._strategy_context("BTCUSDT") is not None

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-long",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="original long thesis",
        position_size_request=0.1,
        leverage_request=10,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    active = await plans.get(plan.trade_plan_id)
    position = await engine.portfolio.get_position("BTCUSDT")
    assert active is not None and active.state == TradePlanState.ACTIVE
    assert active.risk_decision_id is not None
    entry_risk_decision_id = active.risk_decision_id
    assert position is not None and position.quantity == Decimal("0.1")
    assert position.leverage == Decimal("5")
    assert engine.adapter.positions["BTCUSDT"].leverage == Decimal("5")
    entry_order = list(engine.adapter.orders.values())[0]
    persisted_entry = await engine.order_manager.get_by_client(entry_order.client_order_id)
    assert persisted_entry is not None
    assert persisted_entry.metadata["requested_leverage"] == "10.0"
    assert persisted_entry.metadata["approved_leverage"] == "5"

    chief = SequencedChief([("HOLD", "0"), ("REDUCE", "0.04"), ("EXIT", "0")])
    engine.position_manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )

    before_orders = len(engine.adapter.orders)
    hold_decisions = await engine.tick()
    assert hold_decisions == []
    assert len(engine.adapter.orders) == before_orders
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    clock.advance()
    reduction_decisions = await engine.tick()
    assert reduction_decisions[0].checks["original_direction"] == "LONG"
    await engine.wait_for_event_queue()
    reduced = await engine.portfolio.get_position("BTCUSDT")
    assert reduced is not None and reduced.quantity == Decimal("0.06")
    assert reduced.leverage == Decimal("5")
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    reduction_order = list(engine.adapter.orders.values())[-1]
    persisted_reduction = await engine.order_manager.get_by_client(
        reduction_order.client_order_id
    )
    assert persisted_reduction is not None
    assert persisted_reduction.metadata["reduce_only"] is True
    assert persisted_reduction.metadata["risk_decision_id"] != entry_risk_decision_id
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []

    clock.advance()
    exit_decisions = await engine.tick()
    assert exit_decisions[0].checks["original_direction"] == "LONG"
    submitted = await plans.get(plan.trade_plan_id)
    assert submitted is not None
    assert submitted.state == TradePlanState.ACTIVE
    assert submitted.exit_decision_id is None
    await engine.wait_for_event_queue()
    closed_position = await engine.portfolio.get_position("BTCUSDT")
    closed_plan = await plans.get(plan.trade_plan_id)
    assert closed_position is not None and closed_position.quantity == 0
    assert closed_plan is not None and closed_plan.state == TradePlanState.CLOSED
    assert closed_plan.risk_decision_id == entry_risk_decision_id
    assert closed_plan.exit_decision_id == "position-3-exit"
    assert closed_plan.terminal_reason == "EXIT"
    assert closed_plan.closed_at is not None
    assert chief.calls == 3

    async with database.session_factory() as session:
        episodes = (await session.execute(select(TradeEpisodeORM))).scalars().all()
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode.trade_plan_id == plan.trade_plan_id
        assert episode.entry_decision_id == "entry-long"
        assert episode.exit_decision_id == "position-3-exit"
        assert episode.position_decision_ids_json == [
            "position-1-hold",
            "position-2-reduce",
            "position-3-exit",
        ]
        assert len(episode.order_ids_json) == 3
        assert len(episode.fill_ids_json) == 3
        assert episode.risk_decision_ids_json == [
            entry_risk_decision_id,
            persisted_reduction.metadata["risk_decision_id"],
            list(engine.adapter.orders.values())[-1].metadata["risk_decision_id"],
        ]
        assert episode.opened_quantity == Decimal("0.1")
        assert episode.closed_quantity == Decimal("0.1")
        assert episode.factual is True
        assert episode.review_status == "PENDING"

    duplicate = await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id)
    assert duplicate is not None and duplicate.episode_id == episode.episode_id
    review = await DailyReviewScheduler(
        database.session_factory, canonical_only=True
    ).run_once(episode.closed_at.date().isoformat())
    assert review["trade_count"] == 1
    duplicate_review = await DailyReviewScheduler(
        database.session_factory, canonical_only=True
    ).run_once(episode.closed_at.date().isoformat())
    assert duplicate_review["trade_count"] == 1
    async with database.session_factory() as session:
        episodes = (await session.execute(select(TradeEpisodeORM))).scalars().all()
        assert len(episodes) == 1
        assert episodes[0].review_status == "REVIEWED"
        reviews = (await session.execute(select(AITradeReviewORM))).scalars().all()
        patterns = (await session.execute(select(AIMarketPatternORM))).scalars().all()
        assert len(reviews) == 1
        assert reviews[0].episode_id == episode.episode_id
        assert reviews[0].mistakes_json == []
        assert len(patterns) == 1
        assert patterns[0].sample_count == 1

    loader = ChiefContextLoader(database.session_factory)
    chief_context = ChiefTraderContext(
            symbol="BTCUSDT",
            market_snapshot={},
            regime="TREND",
            quant_evidence=[],
            portfolio_state={},
            risk_summary={},
        )
    enriched = await loader.enrich(chief_context)
    assert enriched.episode_refs == [episode.episode_id]
    assert enriched.memory_refs == [f"review:{episode.episode_id}"]
    episode_evidence = await loader.load_tool("episode_search", chief_context)
    memory_evidence = await loader.load_tool("memory_search", chief_context)
    pattern_evidence = await loader.load_tool("factor_intelligence", chief_context)
    assert episode_evidence.source_refs == [f"episode:{episode.episode_id}"]
    assert memory_evidence.source_refs == [f"memory:review:{episode.episode_id}"]
    assert pattern_evidence.source_refs == [f"pattern:{patterns[0].pattern_id}"]
    assert enriched.similar_episodes[0]["net_pnl"] == str(episode.net_pnl)
    assert enriched.pattern_refs == [patterns[0].pattern_id]
    async with database.session_factory() as session:
        stored_episode = await session.get(TradeEpisodeORM, episode.episode_id)
        stored_episode.closed_at = datetime(2026, 1, 1, 23, tzinfo=UTC)
        await session.commit()
    local_day = await TradeEpisodeStore(database.session_factory).load_closed_on(
        "2026-01-02",
        timezone=timezone(timedelta(hours=12)),
    )
    assert [item.episode_id for item in local_day] == [episode.episode_id]
    await engine.stop()


async def test_short_reduce_exit_is_factual_reduce_only_and_never_reverses(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-short-lifecycle")
    assert await engine._strategy_context("BTCUSDT") is not None

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-short",
        symbol="BTCUSDT",
        action="SHORT",
        market_regime="DOWNTREND",
        thesis="original short thesis",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=105,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("99"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    opened = await engine.portfolio.get_position("BTCUSDT")
    assert opened is not None and opened.quantity == Decimal("-0.1")
    assert opened.instrument_type == "LINEAR_PERP"
    assert opened.leverage == Decimal("2")
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    chief = SequencedChief([("REDUCE", "0.04"), ("EXIT", "0")])
    engine.position_manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    reduction_decisions = await engine.tick()
    assert reduction_decisions[0].checks["original_direction"] == "SHORT"
    await engine.wait_for_event_queue()
    reduced = await engine.portfolio.get_position("BTCUSDT")
    assert reduced is not None and reduced.quantity == Decimal("-0.06")
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    clock.advance()
    exit_decisions = await engine.tick()
    assert exit_decisions[0].checks["original_direction"] == "SHORT"
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    await engine.wait_for_event_queue()
    closed = await engine.portfolio.get_position("BTCUSDT")
    final_plan = await plans.get(plan.trade_plan_id)
    assert closed is not None and closed.quantity == 0
    assert final_plan is not None and final_plan.state == TradePlanState.CLOSED
    assert final_plan.exit_decision_id == "position-2-exit"
    assert all(order.side.value == "BUY" for order in list(engine.adapter.orders.values())[1:])
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
        assert episode.direction == "SHORT"
        assert episode.opened_quantity == Decimal("0.1")
        assert episode.closed_quantity == Decimal("0.1")
        assert episode.gross_pnl == Decimal("-0.0001")
    await engine.stop()


async def test_partial_exit_fill_stays_active_until_factual_remaining_position_closes(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-partial-exit")
    assert await engine._strategy_context("BTCUSDT") is not None
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-partial-exit",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="factual partial-exit thesis",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    book = engine.adapter.books["BTCUSDT"]
    book.apply_snapshot(
        engine.adapter.sequence["BTCUSDT"] + 1,
        [(Decimal("99.95"), Decimal("0.04"))],
        [(Decimal("100.05"), Decimal("1"))],
    )
    engine.position_manager = LiveLLMPositionManager(
        chief=SequencedChief([("EXIT", "0"), ("EXIT", "0")]),
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    await engine.tick()
    await engine.wait_for_event_queue()

    partially_closed = await engine.portfolio.get_position("BTCUSDT")
    partial_plan = await plans.get(plan.trade_plan_id)
    partial_order = list(engine.adapter.orders.values())[-1]
    assert partially_closed is not None and partially_closed.quantity == Decimal("0.06")
    assert partial_plan is not None and partial_plan.state == TradePlanState.ACTIVE
    assert partial_plan.exit_decision_id is None
    assert partial_order.status == OrderStatus.PARTIALLY_FILLED

    await engine.adapter.cancel_order("BTCUSDT", partial_order.exchange_order_id)
    await engine.wait_for_event_queue()
    engine.adapter.seed_book("BTCUSDT")
    clock.advance()
    await engine.tick()
    await engine.wait_for_event_queue()

    closed = await engine.portfolio.get_position("BTCUSDT")
    closed_plan = await plans.get(plan.trade_plan_id)
    assert closed is not None and closed.quantity == 0
    assert closed_plan is not None and closed_plan.state == TradePlanState.CLOSED
    assert closed_plan.exit_decision_id == "position-2-exit"
    await engine.stop()


async def test_position_action_waits_until_partially_filled_entry_order_is_terminal(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-entry-fill-race")
    assert await engine._strategy_context("BTCUSDT") is not None

    book = engine.adapter.books["BTCUSDT"]
    book.apply_snapshot(
        engine.adapter.sequence["BTCUSDT"] + 1,
        [(Decimal("99.95"), Decimal("1"))],
        [(Decimal("100.05"), Decimal("0.04"))],
    )
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-fill-race",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="partial entry must settle before exit",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    entry_order = list(engine.adapter.orders.values())[0]
    position = await engine.portfolio.get_position("BTCUSDT")
    assert entry_order.status == OrderStatus.PARTIALLY_FILLED
    assert position is not None and position.quantity == Decimal("0.04")
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    engine.position_manager = LiveLLMPositionManager(
        chief=SequencedChief([("EXIT", "0"), ("EXIT", "0")]),
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    result = await engine.tick()
    await engine.wait_for_event_queue()

    assert result == []
    assert len(engine.adapter.orders) == 1
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    assert (await engine.portfolio.get_position("BTCUSDT")).quantity == Decimal("0.04")
    assert (await engine.order_manager.get(entry_order.internal_order_id)).status == (
        OrderStatus.CANCELLED
    )

    engine.adapter.seed_book("BTCUSDT")
    clock.advance()
    await engine.tick()
    await engine.wait_for_event_queue()

    assert len(engine.adapter.orders) == 2
    assert (await engine.portfolio.get_position("BTCUSDT")).quantity == 0
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.CLOSED
    await engine.stop()


async def test_time_stop_is_only_a_max_hold_reduce_only_fallback(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-time-stop")
    assert await engine._strategy_context("BTCUSDT") is not None

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-time-stop",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="time bounded thesis",
        position_size_request=0.1,
        leverage_request=1,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(
        plans, max_holding_time_seconds=60
    ).create_entry_signal(entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    chief = SequencedChief([("HOLD", "0"), ("REDUCE", "0.01")])
    engine.position_manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    order_count = len(engine.adapter.orders)
    await engine.tick()
    assert len(engine.adapter.orders) == order_count
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    clock.advance(61)
    await engine.tick()
    submitted = list(engine.adapter.orders.values())[-1]
    assert submitted.metadata["reduce_only"] is True
    assert submitted.metadata["time_stop"] is True
    assert submitted.metadata["lifecycle_action"] == "TIME_STOP_SAFETY_FALLBACK"
    await engine.wait_for_event_queue()
    assert (await engine.portfolio.get_position("BTCUSDT")).quantity == 0
    closed = await plans.get(plan.trade_plan_id)
    assert closed.state == TradePlanState.CLOSED
    assert closed.terminal_reason == "TIME_STOP_SAFETY_FALLBACK"
    await engine.stop()


async def test_duplicate_exit_ticks_create_one_pending_close_lifecycle(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-duplicate-exit")
    assert await engine._strategy_context("BTCUSDT") is not None
    plans = TradePlanService(database.session_factory)
    decisions = LLMDecisionStore(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-duplicate-exit",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="durable duplicate-exit thesis",
        position_size_request=0.1,
        leverage_request=1,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    # Leave the first close order resting so the next LLM tick exercises the
    # persisted TradePlan-level guard rather than client-id idempotency.
    match_order = engine.adapter._match_order
    engine.adapter._match_order = lambda _order: []
    engine.position_manager = LiveLLMPositionManager(
        chief=SequencedChief([("EXIT", "0"), ("EXIT", "0")]),
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    await engine.tick()
    assert len(engine.adapter.orders) == 2
    assert await engine.order_manager.has_pending_position_action(plan.trade_plan_id)
    pending = await plans.get(plan.trade_plan_id)
    assert pending is not None and pending.state == TradePlanState.ACTIVE
    assert pending.exit_decision_id is None

    engine.adapter._match_order = match_order
    clock.advance()
    await engine.tick()
    assert len(engine.adapter.orders) == 2
    pending = await plans.get(plan.trade_plan_id)
    assert pending is not None and pending.state == TradePlanState.ACTIVE
    assert pending.exit_decision_id is None
    await engine.stop()


async def test_expired_entry_is_terminal_before_order_creation(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-expired-entry")
    assert await engine._strategy_context("BTCUSDT") is not None
    plans = TradePlanService(database.session_factory)
    decisions = LLMDecisionStore(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-expired",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="expired factual opportunity",
        position_size_request=0.1,
        leverage_request=1,
        stop_loss=95,
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    signal = signal.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    await engine.process_signal(signal)
    expired = await plans.get(plan.trade_plan_id)
    assert expired is not None and expired.state == TradePlanState.EXPIRED
    assert expired.terminal_reason == "ORDER_EXPIRED"
    assert engine.adapter.orders == {}
    await engine.stop()


async def test_cancelled_unfilled_entry_cancels_approved_trade_plan(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-cancelled-entry")
    assert await engine._strategy_context("BTCUSDT") is not None
    plans = TradePlanService(database.session_factory)
    decisions = LLMDecisionStore(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-cancelled",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="resting factual opportunity",
        position_size_request=0.1,
        leverage_request=1,
        stop_loss=95,
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("99.5"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await engine.process_signal(signal)
    approved = await plans.get(plan.trade_plan_id)
    assert approved is not None and approved.state == TradePlanState.APPROVED
    order = next(iter(engine.adapter.orders.values()))
    await engine.adapter.cancel_order(order.symbol, order.exchange_order_id)
    await engine.wait_for_event_queue()
    cancelled = await plans.get(plan.trade_plan_id)
    assert cancelled is not None and cancelled.state == TradePlanState.CANCELLED
    assert cancelled.terminal_reason == "ORDER_CANCELLED"
    await engine.stop()


async def test_paper_restart_restores_active_position_without_fabricating_fill(database):
    first = make_paper_engine(database, engine_tick_seconds=3600)
    await first.start("run-before-restart")
    assert await first._strategy_context("BTCUSDT") is not None
    plans = TradePlanService(database.session_factory)
    decisions = LLMDecisionStore(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-restart",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="durable restart thesis",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=first.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await first.process_signal(signal)
    await first.wait_for_event_queue()
    fills_before = len(first.adapter.event_log)
    expected = await first.portfolio.get_position("BTCUSDT")
    assert expected is not None and expected.quantity == Decimal("0.1")
    await first.stop()

    recovered = make_paper_engine(database, engine_tick_seconds=3600)
    await recovered.start("run-after-restart")
    restored = await recovered.adapter.get_positions()
    assert len(restored) == 1
    assert restored[0].quantity == expected.quantity
    assert restored[0].avg_entry_price == expected.avg_entry_price
    assert restored[0].contract_size == expected.contract_size
    assert restored[0].leverage == expected.leverage
    assert recovered.adapter.event_log == []
    assert fills_before > 0
    report = await recovered.reconciliation.reconcile(recovered.adapter)
    assert report.ok is True
    assert report.halt is False
    assert recovered.runtime_snapshot()["health"]["components"][
        "paper_restart_recovery"
    ]["ok"] is True
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    await recovered.stop()


@pytest.mark.parametrize(
    ("action", "expected_side", "stop_loss", "limit_price"),
    [("LONG", "BUY", 95, "101"), ("SHORT", "SELL", 105, "99")],
)
async def test_risk_scale_down_quantity_reaches_existing_order_path(
    database, action, expected_side, stop_loss, limit_price
):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.risk_engine.config.max_order_notional = Decimal(limit_price) * Decimal("0.01")
    await engine.start("run-risk-scale-down")
    assert await engine._strategy_context("BTCUSDT") is not None
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id=f"entry-risk-scale-down-{action.lower()}",
        symbol="BTCUSDT",
        action=action,
        market_regime="TREND",
        thesis=f"direction remains {action.lower()} after magnitude clamp",
        position_size_request=2,
        leverage_request=2,
        stop_loss=stop_loss,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal(limit_price),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)

    risk = await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    assert risk is not None and risk.decision == ExecutionDecision.SCALE_DOWN
    assert risk.side.value == expected_side
    assert risk.checks["original_quantity"] == "2.0"
    assert risk.checks["approved_quantity"] == "1"
    order = list(engine.adapter.orders.values())[-1]
    assert order.side.value == expected_side
    assert order.quantity == Decimal("1")
    assert order.metadata["trade_plan_id"] == plan.trade_plan_id
    assert order.metadata["decision_id"] == entry.decision_id
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    await engine.stop()
