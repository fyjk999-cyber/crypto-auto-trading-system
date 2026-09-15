"""Phase 7 race/authority matrix: exit-coordination races (SPEC priority order).

These tests exercise the canonical ExitCoordinator invariants directly:
    TotalReduceQty <= CurrentFactualPositionQty
with the fixed priority:
    Risk Hard Exit > Offline Hard Exit > Fast Profit > Base Exit >
    LLM Reduce/Close > LLM New Risk.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.exit_coordinator import ExitCoordinator, ExitPriority


def _coordinator(qty: str = "1") -> ExitCoordinator:
    coordinator = ExitCoordinator()
    coordinator.register_leg("leg1", symbol="BTCUSDT", side="LONG", quantity=Decimal(qty))
    return coordinator


def _submit(coordinator, qty: str, priority: ExitPriority, request_id: str):
    return coordinator.submit(
        leg_id="leg1",
        side=OrderSide.SELL,
        quantity=Decimal(qty),
        priority=priority,
        reason_code=priority.name,
        authority="TEST",
        request_id=request_id,
    )


def test_fast_profit_partial_then_base_exit_never_oversells() -> None:
    coordinator = _coordinator("1")
    fast = _submit(coordinator, "0.4", ExitPriority.FAST_PROFIT, "fast-1")
    assert fast.accepted is True

    base = _submit(coordinator, "1", ExitPriority.ACTIVE_BASE_EXIT, "base-1")
    # Base Exit is lower priority: it may only take what is still unreserved.
    assert base.approved_qty <= Decimal("0.6")
    assert coordinator.reserved_qty("leg1") <= Decimal("1")
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["invariant_holds"] is True


def test_risk_hard_exit_preempts_pending_base_exit() -> None:
    coordinator = _coordinator("1")
    base = _submit(coordinator, "1", ExitPriority.ACTIVE_BASE_EXIT, "base-1")
    assert base.accepted is True

    risk = _submit(coordinator, "1", ExitPriority.RISK_HARD_EXIT, "risk-1")
    assert risk.accepted is True
    assert risk.approved_qty == Decimal("1")
    assert coordinator.reserved_qty("leg1") == Decimal("1")
    # The lower-priority Base Exit no longer holds any capacity.
    assert coordinator.available_qty("leg1") == Decimal("0")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def test_llm_reduce_after_hard_exit_cannot_add_exposure() -> None:
    coordinator = _coordinator("1")
    risk = _submit(coordinator, "1", ExitPriority.RISK_HARD_EXIT, "risk-1")
    assert risk.approved_qty == Decimal("1")

    llm_reduce = _submit(coordinator, "0.5", ExitPriority.LLM_REDUCE_CLOSE, "llm-1")
    assert llm_reduce.approved_qty == Decimal("0")
    assert coordinator.reserved_qty("leg1") == Decimal("1")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def test_fill_consumes_reservation_and_frees_remaining_capacity() -> None:
    coordinator = _coordinator("1")
    base = _submit(coordinator, "0.5", ExitPriority.ACTIVE_BASE_EXIT, "base-1")
    assert base.approved_qty == Decimal("0.5")

    coordinator.confirm_fill("base-1", Decimal("0.5"))
    assert coordinator.legs["leg1"].factual_qty == Decimal("0.5")
    assert coordinator.reserved_qty("leg1") == Decimal("0")

    # Remaining factual capacity can now be used by a later protection.
    remainder = _submit(coordinator, "0.5", ExitPriority.RISK_HARD_EXIT, "risk-2")
    assert remainder.approved_qty == Decimal("0.5")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def test_cancel_then_late_fill_does_not_change_factual_position() -> None:
    coordinator = _coordinator("1")
    base = _submit(coordinator, "0.5", ExitPriority.ACTIVE_BASE_EXIT, "base-cancel")
    assert base.approved_qty == Decimal("0.5")

    coordinator.cancel("base-cancel", reason="CANCEL_FILL_RACE")
    assert coordinator.reserved_qty("leg1") == Decimal("0")

    # The fill event arrives after the cancel: it must be ignored.
    coordinator.confirm_fill("base-cancel", Decimal("0.5"))
    assert coordinator.legs["leg1"].factual_qty == Decimal("1")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def test_duplicate_ws_fill_is_counted_exactly_once() -> None:
    coordinator = _coordinator("1")
    risk = _submit(coordinator, "0.5", ExitPriority.RISK_HARD_EXIT, "risk-dup")
    assert risk.approved_qty == Decimal("0.5")

    coordinator.confirm_fill("risk-dup", Decimal("0.5"))
    first = coordinator.legs["leg1"].factual_qty
    assert first == Decimal("0.5")

    coordinator.confirm_fill("risk-dup", Decimal("0.5"))  # duplicate WS event
    assert coordinator.legs["leg1"].factual_qty == Decimal("0.5")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def test_fill_larger_than_reservation_never_goes_below_zero() -> None:
    coordinator = _coordinator("0.5")
    _submit(coordinator, "0.5", ExitPriority.RISK_HARD_EXIT, "risk-cap")
    coordinator.confirm_fill("risk-cap", Decimal("5"))  # absurd exchange report
    assert coordinator.legs["leg1"].factual_qty == Decimal("0")
    assert coordinator.reserved_qty("leg1") == Decimal("0")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def test_l2_survives_add_and_stays_latched_after_recovery() -> None:
    from crypto_trader.risk.risk_levels import (
        PositionRiskEpisode,
        PositionRiskMonitor,
        RiskLevel,
    )

    monitor = PositionRiskMonitor()
    episode = PositionRiskEpisode(
        leg_id="leg1", symbol="BTCUSDT", side="LONG", entry_price=Decimal("100")
    )
    assert monitor.evaluate(episode, mark_price=Decimal("97.0")).level == RiskLevel.L1

    # An ADD is pending/executed while the warning is live.
    episode.record_add(reason="LLM_ADD")
    assert episode.add_count == 1

    # Deeper collapse while the ADD exists must still force a hard exit.
    l2 = monitor.evaluate(episode, mark_price=Decimal("93.0"))
    assert l2.level == RiskLevel.L2
    assert l2.force_close is True
    assert episode.forced_close is True

    # ADD did not reset the episode; L2 remains latched even after recovery.
    recovered = monitor.evaluate(episode, mark_price=Decimal("105.0"))
    assert recovered.level == RiskLevel.L2
    assert recovered.force_close is True


def test_hard_exit_reservation_revalidates_against_grown_position() -> None:
    coordinator = _coordinator("1")
    risk = _submit(coordinator, "1", ExitPriority.RISK_HARD_EXIT, "risk-grow")
    assert risk.approved_qty == Decimal("1")

    # The pending ADD fills while the hard exit is being executed.
    coordinator.set_factual_qty("leg1", Decimal("1.5"))
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["invariant_holds"] is True
    assert coordinator.reserved_qty("leg1") == Decimal("1")
    assert coordinator.available_qty("leg1") == Decimal("0.5")

    # The additional factual quantity is usable by a later protection.
    follow_up = _submit(coordinator, "0.5", ExitPriority.RISK_HARD_EXIT, "risk-grow-2")
    assert follow_up.approved_qty == Decimal("0.5")
    assert coordinator.snapshot("leg1")["invariant_holds"] is True


def _exit_registry():
    from datetime import UTC, datetime

    from crypto_trader.execution.base_exit import BaseExitRegistry

    base = datetime(2026, 9, 16, tzinfo=UTC)
    registry = BaseExitRegistry()
    v1 = registry.stage(
        "leg1",
        plan_version=1,
        exit_type="PRICE",
        trigger=">=105",
        size_pct=100.0,
        based_on_state_version="pos_v1",
    )
    registry.activate(v1.version_id, factual_state_version="pos_v1", now=base)
    return registry, base


def test_exit_v1_to_v2_race_rejects_resurrecting_old_version() -> None:
    from crypto_trader.execution.base_exit import StaleBaseExitError

    registry, base = _exit_registry()
    old = registry.active("leg1")

    # Position advanced: the LLM produces a fresh v2 exit based on pos_v2.
    v2 = registry.stage(
        "leg1",
        plan_version=2,
        exit_type="PRICE",
        trigger=">=108",
        size_pct=50.0,
        based_on_state_version="pos_v2",
    )
    registry.activate(v2.version_id, factual_state_version="pos_v2", now=base)
    assert registry.active("leg1").version_id == v2.version_id

    # A delayed v1 activation (or replay) must be rejected as stale.
    try:
        registry.activate(old.version_id, factual_state_version="pos_v2", now=base)
    except StaleBaseExitError as exc:
        assert "STALE_DECISION" in str(exc)
    else:
        raise AssertionError("stale v1 exit version must be rejected")
    assert registry.active("leg1").version_id == v2.version_id


def test_exit_activation_after_factual_close_is_rejected() -> None:
    from crypto_trader.execution.base_exit import StaleBaseExitError

    registry, base = _exit_registry()
    registry.mark_filled("leg1", now=base)
    # Leg closed by the factual fill: no new exit may re-open it by accident.
    v2 = registry.stage(
        "leg1",
        plan_version=2,
        exit_type="PRICE",
        trigger=">=108",
        based_on_state_version="pos_v1",
    )
    try:
        registry.activate(v2.version_id, factual_state_version="pos_v1", now=base)
    except StaleBaseExitError as exc:
        assert "STALE_DECISION" in str(exc)
    else:
        raise AssertionError("exit after factual close must be rejected")
