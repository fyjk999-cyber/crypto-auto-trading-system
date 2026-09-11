"""P1-C: factual orphan positions recover only through RECOVERY plans."""

from __future__ import annotations

from datetime import UTC, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.persistence.models import LedgerTransactionORM, PositionProjectionORM
from crypto_trader.strategy.base import StrategyContext
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import Evidence, SequencedChief


def _orphan() -> Position:
    return Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("0.5"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("50"),
        instrument_type="LINEAR_PERP",
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )


async def test_orphan_position_creates_idempotent_recovery_plan_without_fills(database):
    engine = make_paper_engine(database)
    await engine.adapter.connect()
    engine.adapter.positions["BTCUSDT"] = _orphan()
    orders_before = dict(engine.adapter.orders)

    created = await engine._ensure_orphan_recovery_plans()
    assert len(created) == 1
    plan = await TradePlanService(database.session_factory).get_active_for_symbol(
        "BTCUSDT"
    )
    assert plan is not None
    assert plan.state == TradePlanState.RECOVERY
    assert plan.decision_id == "orphan_recovery_BTCUSDT"
    assert plan.direction == "LONG"
    assert plan.max_holding_time_seconds == 1.0
    assert engine.adapter.orders == orders_before

    # No fabricated fill/ledger settlement occurred.
    async with database.session_factory() as session:
        assert (
            await session.execute(select(LedgerTransactionORM))
        ).scalars().all() == []

    # Idempotent restart/retry returns the same recovery lifecycle.
    again = await engine._ensure_orphan_recovery_plans()
    assert again == []  # existing RECOVERY plan is reused
    second_engine = make_paper_engine(database)
    await second_engine.adapter.connect()
    second_engine.adapter.positions["BTCUSDT"] = _orphan()
    restart_created = await second_engine._ensure_orphan_recovery_plans()
    assert restart_created == []  # restart reuses the same lifecycle
    active = await TradePlanService(database.session_factory).get_active_for_symbol(
        "BTCUSDT"
    )
    assert active is not None and active.trade_plan_id == plan.trade_plan_id


async def test_recovery_plan_is_visible_to_position_manager_review(database):
    engine = make_paper_engine(database)
    await engine.adapter.connect()
    engine.adapter.positions["BTCUSDT"] = _orphan()
    await engine._ensure_orphan_recovery_plans()
    plan = await engine.trade_plans.get_active_for_symbol("BTCUSDT")
    assert plan is not None and plan.state == TradePlanState.RECOVERY
    # The normal OPEN-position manager receives the recovery plan; no direct
    # order/fill path exists in orphan recovery itself.
    assert plan.requested_quantity == Decimal("0.5")
    assert plan.exit_conditions == ["FACTUAL_ZERO_POSITION"]


def _review_context(plan, position) -> StrategyContext:
    book = OrderBook(symbol=position.symbol)
    book.apply_snapshot(
        1,
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("100.1"), Decimal("1"))],
    )
    opened = plan.opened_at
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    return StrategyContext(
        symbol=position.symbol,
        book=book,
        account=Account(balances={}, equity=Decimal("10000")),
        positions={position.symbol: position},
        clock_time=opened + timedelta(seconds=5),
        run_id="orphan-review",
        mark_price=Decimal("100"),
    )


async def test_recovery_plan_position_review_produces_normal_reduce_only_signal(database):
    engine = make_paper_engine(database)
    await engine.adapter.connect()
    plans = engine.trade_plans
    plan = await plans.ensure_recovery_plan(
        symbol="BTCUSDT", direction="LONG", quantity=Decimal("0.5")
    )
    position = _orphan()
    manager = LiveLLMPositionManager(
        chief=SequencedChief([("HOLD", "0")]),
        evidence_engine=Evidence(),
        decisions=LLMDecisionStore(database.session_factory),
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=0,
    )
    signal = await manager.review(_review_context(plan, position), position)
    assert signal is not None
    assert signal.metadata["reduce_only"] is True
    assert signal.metadata["trade_plan_id"] == plan.trade_plan_id
    assert signal.quantity == abs(position.quantity)
    stored = await plans.get(plan.trade_plan_id)
    assert stored.latest_position_decision_id is not None
    decision = await LLMDecisionStore(database.session_factory).get(
        stored.latest_position_decision_id
    )
    assert decision is not None and decision.action == "HOLD"
    # HOLD plus max-holding reached becomes a full reduce-only safety EXIT.
    assert signal.metadata["time_stop"] is True


async def test_orphan_recovery_signal_enters_normal_risk_execution_pipeline(database):
    engine = make_paper_engine(database)
    await engine.start("run-orphan-pipeline")
    try:
        await engine.adapter.connect()
        engine.adapter.seed_book("BTCUSDT", mid="100")
        engine._instruments["BTCUSDT"] = Instrument(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            exchange="OKX",
            instrument_type="LINEAR_PERP",
            contract_size=Decimal("0.01"),
            contract_multiplier=Decimal("1"),
            tick_size=Decimal("0.1"),
            step_size=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            price_precision=1,
            quantity_precision=2,
        )
        plan = await engine.trade_plans.ensure_recovery_plan(
            symbol="BTCUSDT", direction="LONG", quantity=Decimal("0.5")
        )
        async with database.session_factory() as session:
            session.add(
                PositionProjectionORM(
                    account_id="default",
                    symbol="BTCUSDT",
                    base_asset="BTC",
                    quote_asset="USDT",
                    quantity=Decimal("0.5"),
                    avg_entry_price=Decimal("100"),
                    cost_basis=Decimal("50"),
                    instrument_type="LINEAR_PERP",
                    contract_size=Decimal("0.01"),
                    contract_multiplier=Decimal("1"),
                )
            )
            await session.commit()
        position = _orphan()
        manager = LiveLLMPositionManager(
            chief=SequencedChief([("HOLD", "0")]),
            evidence_engine=Evidence(),
            decisions=LLMDecisionStore(database.session_factory),
            plans=engine.trade_plans,
            audit=engine.audit,
            review_cooldown_seconds=0,
        )
        signal = await manager.review(_review_context(plan, position), position)
        assert signal is not None and signal.metadata["reduce_only"] is True
        orders_before = len(engine.adapter.orders)
        risk_decision = await engine.process_signal(signal)
        await engine.wait_for_event_queue()
        assert risk_decision is not None
        assert risk_decision.decision.value == "APPROVE"
        assert risk_decision.checks["reduce_only"] is True
        assert len(engine.adapter.orders) == orders_before + 1
        submitted = list(engine.adapter.orders.values())[-1]
        assert submitted.metadata["reduce_only"] is True
        assert submitted.metadata["trade_plan_id"] == plan.trade_plan_id
        closed = await engine.trade_plans.get(plan.trade_plan_id)
        assert closed is not None and closed.state == TradePlanState.CLOSED
        episode_health = engine.health.snapshot()["components"]["trade_episode"]
        assert episode_health["ok"] is True
        assert episode_health["detail"] == "NOT_APPLICABLE_RECOVERY"
    finally:
        await engine.stop()
