"""Phase 4E/4F tests: event-driven LLM invocation + NEXT_REASSESSMENT.

Proves same-zone oscillation does not spam the Core LLM, material events
bypass dedup, invocation sensitivity scales with position risk, only one
reassessment is active per leg, and NEXT_REASSESSMENT conditions only wake the
LLM (never an order).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.llm_chief import invocation as invocation_module
from crypto_trader.llm_chief import reassessment as reassessment_module
from crypto_trader.llm_chief.invocation import (
    InvocationPriority,
    MaterialEvent,
    ReassessmentInvocationManager,
)
from crypto_trader.llm_chief.reassessment import ReassessmentEvaluator

BASE = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)


def _manager(**kwargs) -> ReassessmentInvocationManager:
    manager = ReassessmentInvocationManager(**kwargs)
    manager.register(
        "leg1",
        symbol="BTCUSDT",
        state_version="v1",
        exposure_usd=Decimal("1000"),
        equity_usd=Decimal("10000"),
        leverage=Decimal("3"),
        notional_usd=Decimal("1000"),
    )
    return manager


def test_same_zone_oscillation_does_not_repeat_invocation() -> None:
    manager = _manager(base_dedup_seconds=1.0)
    first = manager.decide("leg1", now=BASE, price=Decimal("104.00"))
    assert first.should_invoke is True
    manager.complete_invocation("leg1", now=BASE)

    for offset, price in enumerate(("104.01", "103.99", "104.02", "103.98"), start=1):
        decision = manager.decide(
            "leg1", now=BASE + timedelta(seconds=10 * offset), price=Decimal(price)
        )
        assert decision.action == "DEDUPED"
        assert "SAME_ZONE_NO_NEW_INFORMATION" in decision.reason_codes
    assert manager.invocations == 1


def test_material_event_bypasses_dedup_seconds_later() -> None:
    manager = _manager(base_dedup_seconds=30.0)
    manager.decide("leg1", now=BASE, price=Decimal("104.00"))
    manager.complete_invocation("leg1", now=BASE)

    event = MaterialEvent(kind="CVD_REVERSAL", severity=0.9, novelty=0.9, urgency=0.6, at=BASE)
    decision = manager.decide(
        "leg1", now=BASE + timedelta(seconds=3), price=Decimal("104.01"), event=event
    )
    assert decision.should_invoke is True
    assert "DEDUP_BYPASSED" in decision.reason_codes
    assert any("MATERIAL_EVENT" in code for code in decision.reason_codes)


def test_low_novelty_noise_does_not_bypass_dedup() -> None:
    manager = _manager(base_dedup_seconds=30.0)
    manager.decide("leg1", now=BASE, price=Decimal("104.00"))
    manager.complete_invocation("leg1", now=BASE)
    noise = MaterialEvent(kind="CVD_REVERSAL", severity=0.9, novelty=0.01, at=BASE)
    decision = manager.decide(
        "leg1", now=BASE + timedelta(seconds=2), price=Decimal("104.01"), event=noise
    )
    assert decision.action == "DEDUPED"


def test_large_leveraged_position_has_higher_sensitivity_and_priority() -> None:
    small = _manager()
    small.update_position(
        "leg1",
        state_version="v2",
        exposure_usd=Decimal("200"),
        equity_usd=Decimal("10000"),
        leverage=Decimal("1"),
        unrealized_pnl_pct=0.0,
    )
    big = _manager()
    big.update_position(
        "leg1",
        state_version="v2",
        exposure_usd=Decimal("9000"),
        equity_usd=Decimal("10000"),
        leverage=Decimal("18"),
        unrealized_pnl_pct=-6.0,
    )
    event = MaterialEvent(kind="VOLUME_SURGE", severity=0.6, novelty=0.6, at=BASE)
    small_decision = small.decide("leg1", now=BASE, price=Decimal("100"), event=event)
    big_decision = big.decide("leg1", now=BASE, price=Decimal("100"), event=event)
    assert big_decision.sensitivity_score > small_decision.sensitivity_score
    assert big_decision.priority == InvocationPriority.URGENT
    assert small_decision.priority in (InvocationPriority.NORMAL, InvocationPriority.HIGH)


def test_one_active_reassessment_per_leg_and_queued_latest_state() -> None:
    manager = _manager()
    first = manager.decide(
        "leg1",
        now=BASE,
        price=Decimal("100"),
        event=MaterialEvent(kind="LARGE_TRADE", severity=0.8, novelty=0.8, at=BASE),
    )
    assert first.should_invoke is True

    second = manager.decide(
        "leg1",
        now=BASE + timedelta(seconds=1),
        price=Decimal("101"),
        event=MaterialEvent(kind="ORDERBOOK_DISLOCATION", severity=0.9, novelty=0.9, at=BASE),
    )
    assert second.action == "DEFER_ACTIVE"
    assert second.queued_event_kind == "ORDERBOOK_DISLOCATION"

    queued = manager.complete_invocation("leg1", now=BASE + timedelta(seconds=2))
    assert queued is not None and queued.kind == "ORDERBOOK_DISLOCATION"
    snapshot = manager.snapshot("leg1")
    assert snapshot["active"] is True  # queued event immediately started fresh review
    assert manager.deferred == 1


def test_zone_move_after_dedup_window_invokes() -> None:
    manager = _manager(base_dedup_seconds=10.0)
    manager.decide("leg1", now=BASE, price=Decimal("100.00"))
    manager.complete_invocation("leg1", now=BASE)
    moved = manager.decide("leg1", now=BASE + timedelta(seconds=20), price=Decimal("101.5"))
    assert moved.should_invoke is True
    assert "ZONE_MOVED" in moved.reason_codes
    assert moved.state_version == "v1"


def _plan(logic: str, conditions: list[dict]):
    class Plan:
        pass

    plan = Plan()
    plan.logic = logic
    plan.conditions = conditions
    return plan


def test_price_time_indicator_event_conditions() -> None:
    evaluator = ReassessmentEvaluator()
    price_plan = _plan("OR", [{"type": "PRICE", "value": ">=104.5", "priority": "HIGH"}])
    met = evaluator.evaluate(price_plan, now=BASE, price=Decimal("104.8"))
    assert met.triggered is True
    assert met.priority == InvocationPriority.HIGH
    not_met = evaluator.evaluate(price_plan, now=BASE, price=Decimal("104.1"))
    assert not_met.triggered is False

    touch_plan = _plan("OR", [{"type": "PRICE", "value": "104.5"}])
    assert evaluator.evaluate(touch_plan, now=BASE, price=Decimal("104.5")).triggered is True

    time_plan = _plan("OR", [{"type": "TIME", "value": (BASE + timedelta(minutes=5)).isoformat()}])
    assert evaluator.evaluate(time_plan, now=BASE + timedelta(minutes=6)).triggered is True
    assert evaluator.evaluate(time_plan, now=BASE + timedelta(minutes=1)).triggered is False

    indicator_plan = _plan("OR", [{"type": "INDICATOR", "value": "rsi14>=70"}])
    assert (
        evaluator.evaluate(indicator_plan, now=BASE, indicators={"rsi14": 72.5}).triggered is True
    )
    assert (
        evaluator.evaluate(indicator_plan, now=BASE, indicators={"rsi14": 55.0}).triggered is False
    )

    event_plan = _plan("OR", [{"type": "EVENT", "value": "CVD_REVERSAL"}])
    event_wake = evaluator.evaluate(
        event_plan,
        now=BASE,
        events=[MaterialEvent(kind="CVD_REVERSAL", at=BASE - timedelta(seconds=30))],
    )
    assert event_wake.triggered is True
    stale_wake = evaluator.evaluate(
        event_plan,
        now=BASE,
        events=[MaterialEvent(kind="CVD_REVERSAL", at=BASE - timedelta(hours=2))],
    )
    assert stale_wake.triggered is False


def test_and_or_logic_and_priority_escalation() -> None:
    evaluator = ReassessmentEvaluator()
    and_plan = _plan(
        "AND",
        [
            {"type": "PRICE", "value": ">=104.5", "priority": "NORMAL"},
            {"type": "EVENT", "value": "CVD_REVERSAL", "priority": "URGENT"},
        ],
    )
    partial = evaluator.evaluate(and_plan, now=BASE, price=Decimal("105"))
    assert partial.triggered is False
    full = evaluator.evaluate(
        and_plan,
        now=BASE,
        price=Decimal("105"),
        events=[{"kind": "CVD_REVERSAL", "at": BASE.isoformat()}],
    )
    assert full.triggered is True
    assert full.priority == InvocationPriority.URGENT

    or_plan = _plan(
        "OR",
        [
            {"type": "PRICE", "value": ">=104.5", "priority": "NORMAL"},
            {"type": "INDICATOR", "value": "rsi14>=70", "priority": "HIGH"},
        ],
    )
    wake = evaluator.evaluate(or_plan, now=BASE, price=Decimal("100"), indicators={"rsi14": 75})
    assert wake.triggered is True
    assert wake.priority == InvocationPriority.HIGH


def test_malformed_conditions_are_reported_not_crashed() -> None:
    evaluator = ReassessmentEvaluator()
    plan = _plan(
        "OR",
        [
            {"type": "PRICE", "value": "not-a-number"},
            {"type": "INDICATOR", "value": "missing_op"},
            {"type": "WEIRD", "value": "x"},
        ],
    )
    wake = evaluator.evaluate(plan, now=BASE, price=Decimal("100"))
    assert wake.triggered is False
    assert len(wake.unmatched_conditions) == 3


def test_invocation_and_reassessment_have_no_order_authority() -> None:
    for module in (invocation_module, reassessment_module):
        source = inspect.getsource(module)
        for forbidden in (
            "ExecutionAuthority",
            "OrderManager",
            "submit_order",
            "process_signal",
            "SignalIntent",
        ):
            assert forbidden not in source
    wake = ReassessmentEvaluator().evaluate(
        _plan("OR", [{"type": "PRICE", "value": ">=1"}]), now=BASE, price=Decimal("2")
    )
    assert wake.is_order is False
    assert wake.authority == "WAKE_LLM_ONLY"
