"""Phase 4 runtime-wiring tests: deterministic exits through the canonical engine.

Proves the existing TradingEngine now executes deterministic protections
(Risk hard exit > Fast Profit > Active Base Exit) through the canonical
reduce-only path without any LLM involvement, with factual orders/fills and
ExitCoordinator reservations consumed by the canonical fill settlement.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.exit_coordinator import ExitCoordinator, ExitPriority
from crypto_trader.factors.expert.context import AllInCostEstimate
from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.runtime.exit_controller import DeterministicExitController
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine


async def _open_v2_position(engine, database, *, base_trigger: str = ">=1") -> str:
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="det-entry",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="deterministic exit wiring test",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=90,
        plan_contract_version=2,
        capital_allocation_pct=20.0,
        strategy="BREAKOUT",
        base_exit=BaseExitPlan(
            type="PRICE", trigger=base_trigger, size_pct=100, reason_code="BASE_EXIT"
        ),
        based_on_state_version="entry_v1",
        expected_edge_bps=50.0,
        expected_cost_bps=10.0,
        model_provider="deepseek",
        model="deepseek-chat",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="det-test")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101")
    )
    assert plan is not None and signal is not None
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is not None and position.quantity > 0
    active = await engine.trade_plans.get(plan.trade_plan_id)
    assert active is not None and active.state == TradePlanState.ACTIVE
    return plan.trade_plan_id


async def test_engine_executes_active_base_exit_without_llm(database) -> None:
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-det-base-exit")
    assert await engine._strategy_context("BTCUSDT") is not None

    plan_id = await _open_v2_position(engine, database, base_trigger=">=1")
    # No position_manager is wired: the deterministic protection must not
    # depend on an LLM review to fire.
    assert engine.position_manager is None

    before = await engine.portfolio.get_position("BTCUSDT")
    assert before is not None and before.quantity > 0

    await engine.tick()
    await engine.wait_for_event_queue()

    after = await engine.portfolio.get_position("BTCUSDT")
    assert after is None or after.quantity == 0

    orders = await engine.order_manager.list_all(limit=50)
    exit_orders = [
        order for order in orders if order.metadata.get("exit_authority") == "ACTIVE_BASE_EXIT"
    ]
    assert exit_orders, "deterministic Base Exit must produce a canonical order"
    assert any(order.status.value == "FILLED" for order in exit_orders)
    assert all(order.metadata.get("reduce_only") is True for order in exit_orders)
    assert all(order.metadata.get("trade_plan_id") == plan_id for order in exit_orders)

    snapshot = engine.exit_controller.snapshot(plan_id)
    assert snapshot["registered"] is True
    assert snapshot["coordinator"]["invariant_holds"] is True
    assert Decimal(snapshot["coordinator"]["reserved_reduce_qty"]) == 0

    await engine.stop()


def test_risk_l2_outranks_base_exit_and_gets_100_pct() -> None:
    controller = DeterministicExitController(
        coordinator=ExitCoordinator(),
        costs=AllInCostEstimate(),
    )
    controller.ensure_leg(
        leg_id="leg-risk",
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        state_version="v1",
        base_exit={
            "type": "PRICE",
            "trigger": ">=1",
            "size_pct": 50,
            "reason_code": "BASE_EXIT",
        },
    )
    intents = controller.evaluate("leg-risk", price=Decimal("93"))  # -7% -> L2
    assert len(intents) == 1
    intent = intents[0]
    assert intent.authority == "RISK_HARD_EXIT"
    assert intent.priority == ExitPriority.RISK_HARD_EXIT
    assert intent.exit_pct == 100.0
    assert intent.quantity == Decimal("1")
    assert intent.is_new_risk is False
    # The Base Exit was not emitted (risk hard exit wins).
    assert all(item.authority != "ACTIVE_BASE_EXIT" for item in intents)


def test_risk_l1_returns_llm_wake_intent_without_quantity() -> None:
    controller = DeterministicExitController()
    controller.ensure_leg(
        leg_id="leg-l1",
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        state_version="v1",
    )
    intents = controller.evaluate("leg-l1", price=Decimal("97.5"))  # -2.5% -> L1
    wake = [item for item in intents if item.requires_llm_reassessment]
    assert wake, "L1 must request a Core LLM reassessment"
    assert wake[0].quantity == Decimal("0")
    assert wake[0].reason_code == "RISK_L1_LLM_REASSESSMENT"
    assert all(item.authority != "FAST_PROFIT_PROTECTION" for item in intents)


def test_controller_reservations_never_exceed_factual_position() -> None:
    controller = DeterministicExitController()
    controller.ensure_leg(
        leg_id="leg-cap",
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        state_version="v1",
        base_exit={"type": "PRICE", "trigger": ">=1", "size_pct": 100},
    )
    first = controller.evaluate("leg-cap", price=Decimal("100"))
    assert first and first[0].quantity == Decimal("2")
    second = controller.evaluate("leg-cap", price=Decimal("101"))
    # No capacity left: the second attempt must not duplicate/oversell.
    assert second == []
    assert controller.rejected_intents
    assert controller.coordinator.reserved_qty("leg-cap") <= Decimal("2")
    assert controller.coordinator.reserved_qty("leg-cap") == Decimal("2")
    assert controller.coordinator.snapshot("leg-cap")["invariant_holds"] is True


def test_exit_side_for_short_leg_is_buy() -> None:
    controller = DeterministicExitController()
    controller.ensure_leg(
        leg_id="leg-short",
        symbol="BTCUSDT",
        side="SHORT",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        state_version="v1",
        base_exit={"type": "PRICE", "trigger": ">=1", "size_pct": 100},
    )
    intents = controller.evaluate("leg-short", price=Decimal("99"))
    assert intents
    request = controller.coordinator.requests[intents[0].reservation_request_id]
    assert request.side == OrderSide.BUY
