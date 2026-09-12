"""P1: stale partial position-action liveness (authorised policy: cancel-only).

A position-reducing order resting at PARTIALLY_FILLED blocks every later
REDUCE/EXIT through the duplicate guard — correctly, because a resting order IS
pending and a second independent order could over-reduce or flip the position.
What must not happen is the resulting management gap becoming permanent and
invisible: an order 5x past the stale threshold with 2 of 138 filled blocked 31
consecutive ChiefTrader EXIT intents on the live runtime.

Authorised policy is RECONCILE_THEN_CANCEL_ONLY:
  reconcile first (a last-moment fill must be consumed, not cancelled away),
  cancel only when the refreshed class is still STALE,
  never act on an ambiguous (UNKNOWN / CANCEL_PENDING) state,
  never replace, reprice, convert to market or resubmit,
  and let the newest intent come from a FRESH ChiefTrader review.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.order.manager import (
    DEFAULT_STALE_POSITION_ACTION_SECONDS,
    POSITION_ACTION_RECONCILIATION_REQUIRED,
    POSITION_ACTION_RESTING_VALID,
    POSITION_ACTION_STALE,
    POSITION_ACTION_TERMINAL,
    OrderManager,
)

SYMBOL = "CPUSDT"
PLAN = "plan_1"


class _Row:
    def __init__(self, *, created_at, quantity="138", filled="2", status="PARTIALLY_FILLED"):
        self.internal_order_id = "ord_partial"
        self.quantity = Decimal(quantity)
        self.filled_quantity = Decimal(filled)
        self.status = status
        self.created_at = created_at
        self.metadata_json = {"trade_plan_id": PLAN}


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_a, **_k):
        return _Result(self._rows)

    async def get(self, _model, _pk):
        return self._rows[0] if self._rows else None


def _manager(rows, *, stale_after=DEFAULT_STALE_POSITION_ACTION_SECONDS):
    return OrderManager(lambda *a, **k: _Session(rows), stale_position_action_seconds=stale_after)


def _age(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


# ------------------------------------------------------------------ P1-T1
def test_P1_T1_fresh_partial_order_is_resting_valid_and_not_cancelled():
    rows = [_Row(created_at=_age(30))]
    manager = _manager(rows)
    facts = _run(manager.pending_position_action_facts(PLAN))
    assert facts["classification"] == POSITION_ACTION_RESTING_VALID
    assert facts["stale"] is False
    assert facts["remaining_quantity"] == "136"


# ------------------------------------------------------------------ P1-T2
def test_P1_T2_stale_partial_order_classifies_stale_for_cancellation():
    rows = [_Row(created_at=_age(5 * DEFAULT_STALE_POSITION_ACTION_SECONDS))]
    manager = _manager(rows)
    reconciled = _run(manager.reconcile_pending_position_action("ord_partial"))
    assert reconciled["classification"] == POSITION_ACTION_STALE
    assert reconciled["remaining_quantity"] == "136"
    # The guard itself still reports the order as blocking: liveness adds
    # observability and a cancel path, never permission to duplicate.
    assert _run(manager.has_pending_position_action(PLAN)) is True


# ------------------------------------------------------------------ P1-T3
def test_P1_T3_fill_immediately_before_cancel_is_consumed():
    """A last-moment fill must be consumed, not cancelled away.

    Reconcile re-reads the order, so a fill that landed after the stale
    snapshot is reflected and the classification is re-derived from it.
    """
    stale_snapshot = [_Row(created_at=_age(5 * DEFAULT_STALE_POSITION_ACTION_SECONDS))]
    before = _run(_manager(stale_snapshot).reconcile_pending_position_action("ord_partial"))
    assert before["classification"] == POSITION_ACTION_STALE
    assert before["filled_quantity"] == "2"

    # The fill lands between the snapshot and the cancel attempt.
    after_fill = [
        _Row(created_at=_age(5 * DEFAULT_STALE_POSITION_ACTION_SECONDS), filled="138")
    ]
    after = _run(_manager(after_fill).reconcile_pending_position_action("ord_partial"))
    assert after["filled_quantity"] == "138"
    assert after["remaining_quantity"] == "0"
    # Nothing is left resting, so nothing may be cancelled and no over-reduction
    # can occur from the requested quantity.
    assert after["classification"] == POSITION_ACTION_TERMINAL


# ------------------------------------------------------------------ P1-T4
def test_P1_T4_ambiguous_state_requires_reconciliation_not_cancel():
    for status in ("UNKNOWN", "CANCEL_PENDING"):
        rows = [_Row(created_at=_age(5 * DEFAULT_STALE_POSITION_ACTION_SECONDS), status=status)]
        facts = _run(_manager(rows).reconcile_pending_position_action("ord_partial"))
        assert facts["classification"] == POSITION_ACTION_RECONCILIATION_REQUIRED, status
        assert facts["classification"] != POSITION_ACTION_STALE
        # Still blocking => still fail closed, no second order.
        assert _run(_manager(rows).has_pending_position_action(PLAN)) is True


# ------------------------------------------------------------------ P1-T5
def test_P1_T5_unfilled_remainder_never_changes_position_quantity():
    """Cancel 136 must not move a 275 position: only fills may."""
    rows = [_Row(created_at=_age(5 * DEFAULT_STALE_POSITION_ACTION_SECONDS))]
    facts = _run(_manager(rows).reconcile_pending_position_action("ord_partial"))
    position_before = Decimal("277")
    position_now = position_before - Decimal(facts["filled_quantity"])
    assert position_now == Decimal("275")
    # The requested/remaining quantities must never be used as position truth.
    assert position_before - Decimal(facts["remaining_quantity"]) != position_now
    assert Decimal(facts["quantity"]) != Decimal(facts["filled_quantity"])


# ------------------------------------------------------------------ P1-T6
def test_P1_T6_newer_exit_intent_is_preserved_by_the_blocked_path():
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    src = inspect.getsource(TradingEngine.process_signal)
    assert "latest_intent_preserved" in src
    assert "requested_decision_id" in src
    assert "requested_action" in src
    # The blocked path returns without creating any order.
    assert "return None" in src


# ------------------------------------------------------------------ P1-T7
def test_P1_T7_stale_resolution_rearms_a_fresh_position_review():
    """After a cancel request the newest intent must come from ChiefTrader.

    Asserted structurally: the resolution path requests a cancel, re-arms the
    review state, and never submits a replacement order.
    """
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    src = inspect.getsource(TradingEngine._resolve_stale_position_action)
    assert "POSITION_REVIEW_REARMED_AFTER_STALE_CANCEL" in src
    assert "next_due_at" in src
    # Cancel-only: no new order may be constructed anywhere in this path.
    for forbidden in ("submit_order(", "process_signal(", "create_from_intent("):
        assert forbidden not in src, f"cancel-only path must not submit ({forbidden})"
    assert "cancel_pending" in src
    # Lease-fenced, like every other execution mutation.
    assert "_current_lease_valid" in src


# ------------------------------------------------------------------ P1-T8
def test_P1_T8_duplicate_guard_and_fail_closed_are_preserved():
    """The guard keeps every blocking status and the cancel path fails closed."""
    import inspect

    from crypto_trader.order.manager import OrderManager as OM
    from crypto_trader.runtime.engine import TradingEngine

    guard = inspect.getsource(OM.has_pending_position_action)
    for status in (
        "CREATED", "VALIDATED", "SUBMITTING", "SUBMITTED", "ACKNOWLEDGED",
        "OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING", "UNKNOWN",
    ):
        assert f"OrderStatus.{status}.value" in guard, f"guard lost {status}"

    resolve = inspect.getsource(TradingEngine._resolve_stale_position_action)
    assert "POSITION_ACTION_STALE_CANCEL_UNKNOWN" in resolve
    assert "fail_closed" in resolve


def test_P1_classification_covers_every_blocking_status():
    """No blocking status may fall outside the classification."""
    manager = OrderManager(lambda *a, **k: _Session([]), stale_position_action_seconds=100)
    fresh = 10
    stale = 5 * 100
    for status in ("CREATED", "VALIDATED", "SUBMITTING", "SUBMITTED", "ACKNOWLEDGED", "OPEN"):
        assert manager.classify_pending_position_action(
            status=status, remaining=Decimal("10"), age_seconds=fresh
        ) == POSITION_ACTION_RESTING_VALID
        assert manager.classify_pending_position_action(
            status=status, remaining=Decimal("10"), age_seconds=stale
        ) == POSITION_ACTION_STALE
    assert manager.classify_pending_position_action(
        status="PARTIALLY_FILLED", remaining=Decimal("10"), age_seconds=fresh
    ) == POSITION_ACTION_RESTING_VALID
    assert manager.classify_pending_position_action(
        status="PARTIALLY_FILLED", remaining=Decimal("10"), age_seconds=stale
    ) == POSITION_ACTION_STALE


def _run(coro):
    import asyncio

    return asyncio.run(coro)
