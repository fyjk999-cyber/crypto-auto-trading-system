from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.clock import Clock
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import TradeEpisodeORM
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine


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
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101")
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    active = await plans.get(plan.trade_plan_id)
    position = await engine.portfolio.get_position("BTCUSDT")
    assert active is not None and active.state == TradePlanState.ACTIVE
    assert position is not None and position.quantity == Decimal("0.1")
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
    await engine.tick()
    assert len(engine.adapter.orders) == before_orders
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    clock.advance()
    await engine.tick()
    await engine.wait_for_event_queue()
    reduced = await engine.portfolio.get_position("BTCUSDT")
    assert reduced is not None and reduced.quantity == Decimal("0.06")
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    reduction_order = list(engine.adapter.orders.values())[-1]
    persisted_reduction = await engine.order_manager.get_by_client(
        reduction_order.client_order_id
    )
    assert persisted_reduction is not None
    assert persisted_reduction.metadata["reduce_only"] is True
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []

    clock.advance()
    await engine.tick()
    submitted = await plans.get(plan.trade_plan_id)
    assert submitted is not None
    assert submitted.state == TradePlanState.ACTIVE
    await engine.wait_for_event_queue()
    closed_position = await engine.portfolio.get_position("BTCUSDT")
    closed_plan = await plans.get(plan.trade_plan_id)
    assert closed_position is not None and closed_position.quantity == 0
    assert closed_plan is not None and closed_plan.state == TradePlanState.CLOSED
    assert closed_plan.terminal_reason == "EXIT"
    assert closed_plan.closed_at is not None
    assert chief.calls == 3

    async with database.session_factory() as session:
        episodes = (await session.execute(select(TradeEpisodeORM))).scalars().all()
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode.trade_plan_id == plan.trade_plan_id
        assert episode.entry_decision_id == "entry-long"
        assert episode.position_decision_ids_json == [
            "position-1-hold",
            "position-2-reduce",
            "position-3-exit",
        ]
        assert len(episode.order_ids_json) == 3
        assert len(episode.fill_ids_json) == 3
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
    async with database.session_factory() as session:
        episodes = (await session.execute(select(TradeEpisodeORM))).scalars().all()
        assert len(episodes) == 1
        assert episodes[0].review_status == "REVIEWED"
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
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("99")
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    opened = await engine.portfolio.get_position("BTCUSDT")
    assert opened is not None and opened.quantity == Decimal("-0.1")
    assert opened.instrument_type == "LINEAR_PERP"
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
    await engine.tick()
    await engine.wait_for_event_queue()
    reduced = await engine.portfolio.get_position("BTCUSDT")
    assert reduced is not None and reduced.quantity == Decimal("-0.06")
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE

    clock.advance()
    await engine.tick()
    assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
    await engine.wait_for_event_queue()
    closed = await engine.portfolio.get_position("BTCUSDT")
    final_plan = await plans.get(plan.trade_plan_id)
    assert closed is not None and closed.quantity == 0
    assert final_plan is not None and final_plan.state == TradePlanState.CLOSED
    assert all(order.side.value == "BUY" for order in list(engine.adapter.orders.values())[1:])
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
        assert episode.direction == "SHORT"
        assert episode.opened_quantity == Decimal("0.1")
        assert episode.closed_quantity == Decimal("0.1")
        assert episode.gross_pnl == Decimal("-0.01")
    await engine.stop()
