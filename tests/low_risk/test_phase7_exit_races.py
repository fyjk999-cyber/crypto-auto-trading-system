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
