"""Position-management availability hardening: adversarial counterexamples.

Two independent engineering defects are pinned here.

A. LLM_BUDGET_PRIORITY_INVERSION
   Position management (P0/P1) and new-entry scanning (P2..P5) drew from one
   undifferentiated pool, so a high-frequency review loop could consume the
   whole rolling window and leave an OPEN position with no LLM management path
   for as long as the generating rate exceeded the capacity. The reserve
   mechanism existed but reserved 0 for P0/P1.

B. PARTIAL_REDUCE_ORDER_LIVENESS
   A position-reducing order resting at PARTIALLY_FILLED blocked every later
   REDUCE/EXIT through the duplicate guard — correctly — but with no staleness
   signal the resulting management gap became invisible.

Invariants that must survive both fixes:
   * the duplicate guard is NOT weakened (no second independent reduce/exit),
   * fail-closed is preserved (no deterministic EXIT/REDUCE when the LLM is
     unavailable),
   * the pre-existing ceiling contract is never made stricter.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.llm_chief.budget import (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    P4_MARKET_SELECTION,
    P5_BACKGROUND_RESEARCH,
    REASON_ENTRY_BUDGET_EXHAUSTED,
    REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED,
    STATUS_GRANTED,
    STATUS_SKIPPED_BUDGET,
    BudgetConfig,
    GlobalLLMBudget,
)
from crypto_trader.order.manager import DEFAULT_STALE_POSITION_ACTION_SECONDS


class _FakeClock:
    """Deterministic monotonic clock so window rollover is exact, not timed."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _budget(**kwargs) -> tuple[GlobalLLMBudget, _FakeClock]:
    clock = _FakeClock()
    return GlobalLLMBudget(BudgetConfig(**kwargs), clock=clock), clock


# ===================================================== A. BUDGET PRIORITY (T1-T6)


def test_T1_entry_budget_exhausted_position_management_still_callable():
    """T1: a spent general pool must not strand an OPEN position."""
    budget, _ = _budget(window_seconds=3600, max_calls_per_window=10)
    config = budget.config
    assert config.general_pool == 5  # reserve protection is real, not nominal

    # Drain the general pool with entry decisions.
    for _ in range(config.general_pool):
        assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted

    blocked = budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    assert blocked.granted is False
    assert blocked.reason == REASON_ENTRY_BUDGET_EXHAUSTED

    # The open position still has a management path.
    lifecycle = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review")
    assert lifecycle.granted is True
    assert lifecycle.state == STATUS_GRANTED
    exit_ticket = budget.try_acquire(P0_POSITION_SAFETY, operation="position_exit")
    assert exit_ticket.granted is True


def test_T1b_reserve_cannot_be_spent_by_entry_or_research():
    """The reserve is genuinely protected across every non-position priority."""
    budget, _ = _budget(window_seconds=3600, max_calls_per_window=10)
    pool = budget.config.general_pool
    for priority in (P2_FINAL_ENTRY_DECISION, P4_MARKET_SELECTION, P5_BACKGROUND_RESEARCH):
        while True:
            ticket = budget.try_acquire(priority, operation="non_position")
            if not ticket.granted:
                break
    assert budget.snapshot()["general_calls_in_window"] == pool
    assert budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted


def test_T2_entry_budget_exhausted_without_position_fails_closed():
    """T2: no open position -> entry simply fails closed, no reserve leak."""
    budget, _ = _budget(window_seconds=3600, max_calls_per_window=4)
    granted = 0
    while budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted:
        granted += 1
    assert granted == budget.config.general_pool
    refused = budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    assert refused.granted is False
    assert refused.state == STATUS_SKIPPED_BUDGET
    assert refused.reason == REASON_ENTRY_BUDGET_EXHAUSTED


def test_T3_position_reserve_exhausted_is_explicit_and_distinct():
    """T3: position reserve exhaustion must be its own explicit state.

    The reserve is clamped to the head-room the ceilings already protect, so
    the test asserts the INVARIANT (a positive reserve is honoured, and once
    position management can no longer be granted the reason is the specific
    position-management one) rather than a hardcoded count.
    """
    budget, _ = _budget(
        window_seconds=3600, max_calls_per_window=10, position_management_reserve=6
    )
    reserve = budget.config.reserve_calls
    assert 0 < reserve <= 6
    granted = 0
    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted:
        granted += 1
        assert granted <= budget.config.ceiling_for(P1_POSITION_LIFECYCLE)

    denied = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review")
    assert denied.granted is False
    assert denied.state == STATUS_SKIPPED_BUDGET
    # The whole point: a distinct, actionable reason, not a generic skip.
    assert denied.reason == REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
    assert denied.reason != REASON_ENTRY_BUDGET_EXHAUSTED
    snapshot = budget.snapshot()
    assert snapshot["skipped_by_reason"][REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED] >= 1
    assert snapshot["position_management_calls_in_window"] == granted


def test_T4_window_rollover_restores_capacity():
    """T4: the rolling window must actually release spent capacity."""
    budget, clock = _budget(window_seconds=100, max_calls_per_window=4)
    pool = budget.config.general_pool
    for _ in range(pool):
        assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted
    assert not budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted

    clock.advance(101)
    assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted
    snapshot = budget.snapshot()
    assert snapshot["general_calls_in_window"] == 1


def test_T5_unchanged_state_cannot_storm_the_budget():
    """T5: a blind retry loop on an unchanged position must be capped.

    ``position_review_min_interval_seconds`` bounds the repeat rate, so the
    call count over an hour is bounded rather than unbounded.
    """
    from crypto_trader.config import Settings

    settings = Settings()
    floor = settings.position_review_min_interval_seconds
    assert floor >= settings.engine_tick_seconds, (
        "the coalescing floor must not be tighter than the existing tick contract"
    )
    # Bound: at most one unchanged-position review per floor, per position.
    max_reviews_per_hour = 3600.0 / floor
    assert max_reviews_per_hour <= 120, (
        "one position's unchanged-state review rate must fit the default window"
    )


def test_T5b_material_change_signature_detects_order_state_transitions():
    """T5/T6: size, price AND entry-order state are material.

    Exercised through the engine's own signature so the test fails if the
    material set is ever narrowed.
    """
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    source = inspect.getsource(TradingEngine._position_change_signature)
    for expected in (
        "quantity",
        "avg_entry_price",
        "cost_basis",
        "leverage",
        "realized_pnl",
        "plan_state",
        "entry_order_status",
    ):
        assert expected in source, f"material signature lost {expected}"


def test_T6_ceiling_contract_is_not_made_stricter():
    """Regression guard: the new reserve must never loosen OR over-tighten.

    The pre-existing ceiling behaviour is preserved exactly for tiny windows
    (where the reserve is clamped down to the ceilings' own head-room), and
    position management keeps its guarantee at realistic sizes.
    """
    tiny = BudgetConfig(window_seconds=60, max_calls_per_window=5)
    assert tiny.reserve_calls == 2
    assert tiny.general_pool == 3
    budget = GlobalLLMBudget(tiny)
    # Exactly the pre-existing sequence: three market-selection calls succeed.
    assert budget.try_acquire(P4_MARKET_SELECTION, operation="ms").granted
    assert budget.try_acquire(P4_MARKET_SELECTION, operation="ms").granted
    assert budget.try_acquire(P4_MARKET_SELECTION, operation="ms").granted
    assert not budget.try_acquire(P4_MARKET_SELECTION, operation="ms").granted
    # ...and position safety still has room.
    assert budget.try_acquire(P0_POSITION_SAFETY, operation="exit").granted

    # Ceilings themselves are unchanged by this work.
    default = BudgetConfig(max_calls_per_window=100)
    assert default.ceiling_for(P0_POSITION_SAFETY) == 100
    assert default.ceiling_for(P1_POSITION_LIFECYCLE) == 100
    assert default.ceiling_for(P5_BACKGROUND_RESEARCH) == 55
    # Realistic window: the configured reserve is fully honoured.
    realistic = BudgetConfig(max_calls_per_window=120)
    assert realistic.reserve_calls == 60
    assert realistic.general_pool == 60


def test_T6b_require_position_management_priorities_are_first():
    """The authority order itself must not drift."""
    from crypto_trader.llm_chief.budget import PRIORITY_ORDER

    assert PRIORITY_ORDER[0] == P0_POSITION_SAFETY
    assert PRIORITY_ORDER[1] == P1_POSITION_LIFECYCLE
    assert PRIORITY_ORDER.index(P0_POSITION_SAFETY) < PRIORITY_ORDER.index(
        P2_FINAL_ENTRY_DECISION
    )
    assert PRIORITY_ORDER.index(P1_POSITION_LIFECYCLE) < PRIORITY_ORDER.index(
        P5_BACKGROUND_RESEARCH
    )


# ==================================================== B. PARTIAL ORDER (T7-T12)


class _OrderRow:
    """Minimal factual ORDER row for the liveness helper."""

    def __init__(
        self,
        *,
        order_id: str,
        plan_id: str,
        created_at: datetime,
        quantity: str,
        filled: str,
        status: str,
    ) -> None:
        self.internal_order_id = order_id
        self.quantity = Decimal(quantity)
        self.filled_quantity = Decimal(filled)
        self.status = status
        self.created_at = created_at
        self.metadata_json = {"trade_plan_id": plan_id}


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

    async def execute(self, *_args, **_kwargs):
        return _Result(self._rows)


def _manager(rows, *, stale_after: float = DEFAULT_STALE_POSITION_ACTION_SECONDS):
    from crypto_trader.order.manager import OrderManager

    return OrderManager(
        lambda *a, **k: _Session(rows), stale_position_action_seconds=stale_after
    )


def test_T7_partial_reduce_is_reported_with_factual_remaining_quantity():
    """T7: the pending action exposes remaining quantity and age, and the
    guard is UNCHANGED — a second independent reduce is still suppressed."""
    created = datetime.now(UTC) - timedelta(seconds=30)
    rows = [
        _OrderRow(
            order_id="ord_partial",
            plan_id="plan_1",
            created_at=created,
            quantity="138",
            filled="2",
            status="PARTIALLY_FILLED",
        )
    ]
    manager = _manager(rows)
    assert asyncio.run(manager.has_pending_position_action("plan_1")) is True

    facts = asyncio.run(manager.pending_position_action_facts("plan_1"))
    assert facts is not None
    assert facts["order_id"] == "ord_partial"
    assert facts["remaining_quantity"] == "136"
    assert facts["filled_quantity"] == "2"
    assert facts["stale"] is False  # fresh partial fill is legitimately resting


def test_T8_position_quantity_follows_factual_fills():
    """T8: 277 - 2 = 275 comes from the FILL, not from the order's request."""
    created = datetime.now(UTC)
    rows = [
        _OrderRow(
            order_id="ord_partial",
            plan_id="plan_1",
            created_at=created,
            quantity="138",
            filled="2",
            status="PARTIALLY_FILLED",
        )
    ]
    facts = asyncio.run(_manager(rows).pending_position_action_facts("plan_1"))
    original_position = Decimal("277")
    assert original_position - Decimal(facts["filled_quantity"]) == Decimal("275")
    # The requested-but-unfilled remainder must NOT be deducted.
    assert original_position - Decimal(facts["remaining_quantity"]) != Decimal("275")


def test_T9_stale_partial_order_enters_explicit_review_state():
    """T9: a partial order that outlives the stale window is reported STALE."""
    created = datetime.now(UTC) - timedelta(seconds=2 * DEFAULT_STALE_POSITION_ACTION_SECONDS)
    rows = [
        _OrderRow(
            order_id="ord_stale",
            plan_id="plan_1",
            created_at=created,
            quantity="138",
            filled="2",
            status="PARTIALLY_FILLED",
        )
    ]
    facts = asyncio.run(_manager(rows).pending_position_action_facts("plan_1"))
    assert facts["stale"] is True
    assert facts["age_seconds"] >= DEFAULT_STALE_POSITION_ACTION_SECONDS
    assert facts["remaining_quantity"] == "136"


def test_T9b_fully_filled_or_settled_order_is_never_stale():
    """A terminal order has no remaining quantity, so it cannot block."""
    created = datetime.now(UTC) - timedelta(days=1)
    rows = [
        _OrderRow(
            order_id="ord_done",
            plan_id="plan_1",
            created_at=created,
            quantity="138",
            filled="138",
            status="PARTIALLY_FILLED",
        )
    ]
    facts = asyncio.run(_manager(rows).pending_position_action_facts("plan_1"))
    assert facts["remaining_quantity"] == "0"
    assert facts["stale"] is False


def test_T10_other_plans_and_non_position_orders_never_block():
    """Scope isolation: the liveness report is per trade plan."""
    rows = [
        _OrderRow(
            order_id="ord_other",
            plan_id="plan_OTHER",
            created_at=datetime.now(UTC),
            quantity="10",
            filled="1",
            status="PARTIALLY_FILLED",
        )
    ]
    manager = _manager(rows)
    assert asyncio.run(manager.pending_position_action_facts("plan_1")) is None
    assert asyncio.run(manager.has_pending_position_action("plan_1")) is False


def test_T11_latest_intent_is_preserved_while_pending():
    """T11: the guard must not forget the newest authoritative intent.

    Asserted structurally on the engine: the blocked branch records the
    requested action AND its decision id, so a newer EXIT is observable rather
    than silently discarded, while the refused path still returns None (no
    second order is placed).
    """
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    source = inspect.getsource(TradingEngine.process_signal)
    assert "latest_intent_preserved" in source
    assert "requested_decision_id" in source
    assert "PARTIAL_ORDER_REVIEW_REQUIRED" in source
    assert "pending_position_action_facts" in source


def test_T12_duplicate_guard_and_fail_closed_are_preserved():
    """T12: neither the guard nor fail-closed may be traded away for liveness.

    The pending statuses that make an order blocking must still ALL block,
    including PARTIALLY_FILLED — liveness adds observability, not permission.
    """
    import inspect

    from crypto_trader.order import manager as manager_module
    from crypto_trader.order.manager import OrderManager

    source = inspect.getsource(OrderManager.has_pending_position_action)
    for status in (
        "CREATED",
        "VALIDATED",
        "SUBMITTING",
        "SUBMITTED",
        "ACKNOWLEDGED",
        "OPEN",
        "PARTIALLY_FILLED",
        "CANCEL_PENDING",
        "UNKNOWN",
    ):
        assert f"OrderStatus.{status}.value" in source, f"guard lost {status}"

    # Staleness is a REPORT, never an automatic cancel/replace: assert on the
    # actual call sites, not on prose that may legitimately describe the rule.
    liveness = inspect.getsource(OrderManager.pending_position_action_facts)
    for forbidden in (
        "cancel_pending(",
        "self.cancel(",
        "self.amend(",
        "self.replace(",
        "submit_order(",
    ):
        assert forbidden not in liveness, (
            f"liveness must not perform execution policy ({forbidden})"
        )
    assert hasattr(manager_module, "DEFAULT_STALE_POSITION_ACTION_SECONDS")


def test_T12b_fail_closed_reason_codes_carry_the_precise_cause():
    """Fail-closed keeps its primary code and adds the precise sub-reason."""
    from crypto_trader.llm_chief.context import ChiefTraderContext
    from crypto_trader.llm_chief.decision import PositionState
    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    engine = ChiefTraderEngine(provider=object())
    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        position_state=PositionState.OPEN,
        prepared_at="2026-01-01T00:00:00+00:00",
    )
    decision = engine.fail_closed(
        ctx, "SKIPPED_BUDGET", detail=REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
    )
    assert "SKIPPED_BUDGET" in decision.reason_codes
    assert REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED in decision.reason_codes
    # Never a directional action: budget pressure cannot decide a trade.
    assert decision.action.value == "FAIL_CLOSED"
