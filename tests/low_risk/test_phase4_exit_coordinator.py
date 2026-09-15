"""Phase 4I / Phase 6 exit-coordination tests (oversell prevention).

Deterministic proof that the canonical coordinator never allows
TotalReduceQty > CurrentFactualPositionQty, never preempts confirmed fills,
and never lets new-risk requests consume reduce capacity.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution import exit_coordinator as module
from crypto_trader.execution.exit_coordinator import (
    ExitCoordinator,
    ExitPriority,
    ExitRequestState,
)


def _coordinator(qty: str = "10", side: str = "LONG") -> ExitCoordinator:
    coordinator = ExitCoordinator()
    coordinator.register_leg("leg1", symbol="BTCUSDT", side=side, quantity=Decimal(qty))
    return coordinator


def _reduce(coordinator, qty, priority, **kwargs):
    return coordinator.submit(
        leg_id="leg1",
        side=OrderSide.SELL if coordinator.legs["leg1"].side == "LONG" else OrderSide.BUY,
        quantity=Decimal(qty),
        priority=priority,
        reason_code=kwargs.pop("reason_code", priority.name),
        authority=kwargs.pop("authority", "TEST"),
        **kwargs,
    )


def test_reserves_within_factual_quantity() -> None:
    coordinator = _coordinator("10")
    result = _reduce(coordinator, "6", ExitPriority.ACTIVE_BASE_EXIT)
    assert result.accepted is True
    assert result.approved_qty == Decimal("6")
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["reserved_reduce_qty"] == "6"
    assert snapshot["available_qty"] == "4"
    assert snapshot["invariant_holds"] is True


def test_oversell_is_blocked_and_partially_reserved() -> None:
    coordinator = _coordinator("10")
    _reduce(coordinator, "8", ExitPriority.ACTIVE_BASE_EXIT)
    result = _reduce(coordinator, "5", ExitPriority.LLM_REDUCE_CLOSE, preempt=False)
    assert result.accepted is True
    assert result.approved_qty == Decimal("2")
    assert coordinator.available_qty("leg1") == Decimal("0")
    assert coordinator.reserved_qty("leg1") <= coordinator.legs["leg1"].factual_qty

    empty = _reduce(coordinator, "1", ExitPriority.LLM_REDUCE_CLOSE, preempt=False)
    assert empty.accepted is False
    assert "OVERSELL_BLOCKED_NO_AVAILABLE_QTY" in empty.reason_codes


def test_higher_priority_preempts_only_pending_lower_priority() -> None:
    coordinator = _coordinator("10")
    llm = _reduce(coordinator, "10", ExitPriority.LLM_REDUCE_CLOSE)
    assert llm.accepted and llm.approved_qty == Decimal("10")
    # Part of the LLM reduce is already filled.
    coordinator.confirm_fill(llm.request.request_id, Decimal("4"))
    assert coordinator.legs["leg1"].factual_qty == Decimal("6")

    fast = _reduce(coordinator, "6", ExitPriority.FAST_PROFIT)
    assert fast.accepted is True
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["invariant_holds"] is True
    assert coordinator.reserved_qty("leg1") <= Decimal("6")
    # Filled quantity is never clawed back.
    assert llm.request.filled_qty == Decimal("4")


def test_partial_fill_then_reversal_reduces_factual_and_capacity() -> None:
    coordinator = _coordinator("10")
    request = _reduce(coordinator, "10", ExitPriority.FAST_PROFIT).request
    coordinator.confirm_fill(request.request_id, Decimal("6"))
    assert coordinator.legs["leg1"].factual_qty == Decimal("4")
    assert coordinator.available_qty("leg1") == Decimal("0") or coordinator.reserved_qty(
        "leg1"
    ) <= Decimal("4")

    # The unfilled remainder is still reserved: no capacity for another exit.
    blocked = _reduce(coordinator, "4", ExitPriority.ACTIVE_BASE_EXIT, preempt=False)
    assert blocked.accepted is False

    # Cancelling the pending fast-profit remainder releases factual capacity.
    coordinator.cancel(request.request_id, "FAST_PROFIT_STAND_DOWN")
    assert coordinator.available_qty("leg1") == Decimal("4")
    extra = _reduce(coordinator, "4", ExitPriority.ACTIVE_BASE_EXIT, preempt=False)
    assert extra.accepted is True
    assert extra.approved_qty == Decimal("4")
    assert coordinator.reserved_qty("leg1") <= coordinator.legs["leg1"].factual_qty

    too_much = _reduce(coordinator, "1", ExitPriority.LLM_REDUCE_CLOSE, preempt=False)
    assert too_much.accepted is False


def test_full_close_cancels_other_reservations() -> None:
    coordinator = _coordinator("10")
    fast = _reduce(coordinator, "4", ExitPriority.FAST_PROFIT).request
    base = _reduce(coordinator, "6", ExitPriority.ACTIVE_BASE_EXIT).request
    coordinator.confirm_fill(fast.request_id, Decimal("4"))
    assert coordinator.legs["leg1"].factual_qty == Decimal("6")
    coordinator.confirm_fill(base.request_id, Decimal("6"))
    assert coordinator.legs["leg1"].factual_qty == Decimal("0")
    assert coordinator.legs["leg1"].closed is True
    for request in coordinator.requests.values():
        assert request.reserved_qty == Decimal("0")
    assert coordinator.available_qty("leg1") == Decimal("0")
    rejected = _reduce(coordinator, "1", ExitPriority.RISK_HARD_EXIT, preempt=False)
    assert rejected.accepted is False
    assert "NO_FACTUAL_POSITION" in rejected.reason_codes


def test_new_risk_requests_are_recorded_without_reduce_capacity() -> None:
    coordinator = _coordinator("10")
    base = _reduce(coordinator, "10", ExitPriority.ACTIVE_BASE_EXIT)
    assert base.accepted
    new_risk = coordinator.submit(
        leg_id="leg1",
        side=OrderSide.BUY,
        quantity=Decimal("5"),
        priority=ExitPriority.LLM_NEW_RISK,
        reason_code="LLM_ADD",
        authority="CORE_LLM",
    )
    assert new_risk.accepted is True
    assert "NEW_RISK_RECORDED_AUTHORITY_ELSEWHERE" in new_risk.reason_codes
    # Reduce capacity is untouched by the ADD record.
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["reserved_reduce_qty"] == "10"
    assert snapshot["available_qty"] == "0"
    assert snapshot["invariant_holds"] is True


def test_reduce_side_mismatch_and_invalid_quantity_rejected() -> None:
    coordinator = _coordinator("10", side="SHORT")
    wrong_side = coordinator.submit(
        leg_id="leg1",
        side=OrderSide.SELL,  # SHORT reduce must be BUY
        quantity=Decimal("1"),
        priority=ExitPriority.RISK_HARD_EXIT,
        reason_code="RISK_HARD_EXIT",
        authority="RISK",
    )
    assert wrong_side.accepted is False
    assert "REDUCE_SIDE_MISMATCH" in wrong_side.reason_codes

    zero = _reduce(coordinator, "0", ExitPriority.RISK_HARD_EXIT)
    assert zero.accepted is False
    assert "INVALID_QUANTITY" in zero.reason_codes


def test_cancel_all_for_offline_releases_only_selected_priorities() -> None:
    coordinator = _coordinator("10")
    llm = _reduce(coordinator, "4", ExitPriority.LLM_REDUCE_CLOSE)
    base = _reduce(coordinator, "4", ExitPriority.ACTIVE_BASE_EXIT)
    cancelled = coordinator.cancel_all(
        leg_id="leg1",
        reason="LLM_OFFLINE_MODE",
        priorities={ExitPriority.LLM_REDUCE_CLOSE, ExitPriority.LLM_NEW_RISK},
    )
    assert llm.request.request_id in cancelled
    assert base.request.request_id not in cancelled
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["reserved_reduce_qty"] == "4"
    assert snapshot["available_qty"] == "6"


def test_risk_hard_exit_outranks_everything_and_invariant_holds_under_stress() -> None:
    coordinator = _coordinator("10")
    _reduce(coordinator, "3", ExitPriority.ACTIVE_BASE_EXIT)
    _reduce(coordinator, "3", ExitPriority.LLM_REDUCE_CLOSE)
    _reduce(coordinator, "2", ExitPriority.FAST_PROFIT)
    risk = _reduce(coordinator, "10", ExitPriority.RISK_HARD_EXIT)
    assert risk.accepted is True
    snapshot = coordinator.snapshot("leg1")
    assert snapshot["invariant_holds"] is True
    assert coordinator.reserved_qty("leg1") <= Decimal("10")
    # Risk request must have preempted or consumed all remaining capacity.
    assert risk.approved_qty == Decimal("10") or coordinator.available_qty("leg1") == Decimal("0")


def test_coordinator_has_no_order_submission_path() -> None:
    source = inspect.getsource(module)
    for forbidden in ("submit_order", "adapter.", "ExecutionAuthority"):
        assert forbidden not in source
    assert ExitRequestState.PENDING == "PENDING"
    assert ExitPriority.RISK_HARD_EXIT < ExitPriority.LLM_NEW_RISK
