"""F3: 60s short-term ENTRY TTL (T1-T8) + historical-shape regressions.

Business rule under test: a short-term ENTRY intent does not have an unbounded
lifetime. After 60s an unfilled remainder is reconciled, and only then
cancelled - cancel-ONLY, never replaced, repriced or converted.

Every test asserts on the DECISION plus the SAFETY property, because the danger
here is not "the timer did not fire" but "the timer cancelled something real".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide, OrderStatus
from crypto_trader.order.entry_ttl import (
    ACTION_CANCEL_REMAINING,
    ACTION_HOLD,
    ACTION_NO_CANCEL_ALREADY_PENDING,
    ACTION_NO_CANCEL_TERMINAL,
    ACTION_NO_CANCEL_UNRECONCILED,
    ACTION_NOT_APPLICABLE,
    ENTRY_ORDER_TTL_EXPIRED,
    SHORT_TERM_ENTRY_TTL_SECONDS,
    entry_liveness_eligible,
    evaluate_entry_ttl,
    resting_age_seconds,
)
from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_POSITION_EXIT,
    ORDER_PURPOSE_POSITION_REDUCE,
    RECON_CONFIRMED_CANCELLED,
    RECON_CONFIRMED_FILLED,
    RECON_CONFIRMED_OPEN,
    RECON_CONFIRMED_PARTIALLY_FILLED,
    RECON_MISSING,
    RECON_UNKNOWN,
    classify_order_purpose,
    reconcile_order,
)

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)


class _Order:
    def __init__(
        self,
        *,
        status=OrderStatus.OPEN,
        quantity="1000",
        filled="0",
        exchange_order_id="sim_1",
        symbol="SOPHUSDT",
        side=OrderSide.SELL,
        strategy_id="live_llm",
        reduce_only=None,
    ):
        self.internal_order_id = "ord_ttl"
        self.client_order_id = "cid_ttl"
        self.exchange_order_id = exchange_order_id
        self.symbol = symbol
        self.side = side
        self.status = status
        self.quantity = Decimal(quantity)
        self.filled_quantity = Decimal(filled)
        self.strategy_id = strategy_id
        self.metadata_json = {"reduce_only": reduce_only} if reduce_only is not None else {}


def _fact(*, state, order=None, filled="0", quantity="1000", purpose=ORDER_PURPOSE_ENTRY):
    """Build a reconciliation fact directly in the requested state."""
    if state in (RECON_UNKNOWN, RECON_MISSING):
        return reconcile_order(
            order=order or _Order(filled=filled, quantity=quantity),
            purpose=purpose,
            broker_order=None if state == RECON_MISSING else None,
            broker_error=TimeoutError("x") if state == RECON_UNKNOWN else None,
        )
    broker_status = {
        RECON_CONFIRMED_OPEN: OrderStatus.OPEN,
        RECON_CONFIRMED_PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
        RECON_CONFIRMED_FILLED: OrderStatus.FILLED,
        RECON_CONFIRMED_CANCELLED: OrderStatus.CANCELLED,
    }[state]
    return reconcile_order(
        order=order or _Order(filled=filled, quantity=quantity),
        purpose=purpose,
        broker_order=_Order(status=broker_status, filled=filled, quantity=quantity),
    )


def _age(seconds: float) -> float:
    return seconds


# ------------------------------------------------------------------ T1


def test_T1_within_ttl_does_not_cancel_or_expire():
    """T1: 59s with no fill must NOT cancel and must NOT expire."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_OPEN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=_age(59.0),
    )
    assert decision.action == ACTION_HOLD
    assert decision.reason == "WITHIN_TTL"
    assert decision.should_cancel is False


def test_T1b_wait_just_before_the_boundary():
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_OPEN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=59.999,
    )
    assert decision.should_cancel is False


# ------------------------------------------------------------------ T2


def test_T2_zero_fill_past_ttl_cancels_the_remainder():
    """T2: 60s, 0 filled, confirmed open -> exactly one cancel, remainder only."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_OPEN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=60.0,
    )
    assert decision.action == ACTION_CANCEL_REMAINING
    assert decision.reason == ENTRY_ORDER_TTL_EXPIRED
    assert decision.should_cancel is True
    assert decision.cancel_remaining_only is True
    assert Decimal(decision.remaining_quantity) == Decimal("1000")


# ------------------------------------------------------------------ T3


def test_T3_partial_fill_preserves_the_factual_fill():
    """T3: 300 of 1000 filled -> keep 300, cancel 700, position reflects 300."""
    fact = _fact(
        state=RECON_CONFIRMED_PARTIALLY_FILLED, filled="300", quantity="1000"
    )
    decision = evaluate_entry_ttl(
        fact=fact,
        durable_status=OrderStatus.PARTIALLY_FILLED.value,
        resting_age=60.01,
    )
    assert decision.should_cancel is True
    assert Decimal(decision.filled_quantity) == Decimal("300"), "factual fill lost"
    assert Decimal(decision.remaining_quantity) == Decimal("700")
    assert decision.cancel_remaining_only is True


def test_T3b_nothing_left_to_cancel_when_fully_filled():
    """Guard: a fully-filled remainder is never cancelled away."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_PARTIALLY_FILLED, filled="1000", quantity="1000"),
        durable_status=OrderStatus.PARTIALLY_FILLED.value,
        resting_age=120.0,
    )
    assert decision.should_cancel is False
    assert decision.action == ACTION_NO_CANCEL_TERMINAL


# ------------------------------------------------------------------ T4


def test_T4_filled_state_wins_over_a_fired_timer():
    """T4: the timer fired, but the order is FILLED -> no cancel."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_FILLED, filled="1000"),
        durable_status=OrderStatus.OPEN.value,  # durable row is the stale one
        resting_age=300.0,
    )
    assert decision.action == ACTION_NO_CANCEL_TERMINAL
    assert decision.should_cancel is False
    assert "CONFIRMED_FILLED" in decision.reason


def test_T4b_broker_cancelled_state_is_also_terminal():
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_CANCELLED),
        durable_status=OrderStatus.OPEN.value,
        resting_age=300.0,
    )
    assert decision.should_cancel is False


# ------------------------------------------------------------------ T5


def test_T5_unknown_reconciliation_never_authorises_a_cancel():
    """T5: UNKNOWN != FAILED and != CANCELLED - so it cannot authorise action."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_UNKNOWN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=600.0,
    )
    assert decision.action == ACTION_NO_CANCEL_UNRECONCILED
    assert decision.should_cancel is False
    assert "UNKNOWN" in decision.reason


def test_T5b_missing_reconciliation_is_not_treated_as_cancelled():
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_MISSING),
        durable_status=OrderStatus.OPEN.value,
        resting_age=600.0,
    )
    assert decision.action == ACTION_NO_CANCEL_UNRECONCILED
    assert decision.should_cancel is False
    assert "MISSING" in decision.reason


# ------------------------------------------------------------------ T6


def test_T6_cancel_pending_is_idempotent():
    """T6: repeated cycles while CANCEL_PENDING never re-send a cancel."""
    for _ in range(20):
        decision = evaluate_entry_ttl(
            fact=_fact(state=RECON_CONFIRMED_OPEN),
            durable_status=OrderStatus.CANCEL_PENDING.value,
            resting_age=900.0,
        )
        assert decision.action == ACTION_NO_CANCEL_ALREADY_PENDING
        assert decision.should_cancel is False


# ------------------------------------------------------------------ T7/T8


def test_T7_expired_decision_identity_is_recorded_not_reused():
    """T7: the expiry names the decision so a replay can be refused."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_OPEN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=61.0,
    )
    assert decision.reason == ENTRY_ORDER_TTL_EXPIRED
    # The expiry is an ORDER-LIFECYCLE event; it never carries a direction, so it
    # cannot itself create a new entry and cannot reuse the old decision.
    assert not hasattr(decision, "direction")
    assert "BUY" not in decision.reason and "SELL" not in decision.reason


def test_T8_fresh_direction_is_not_blocked_by_the_expiry():
    """T8: expiry carries no directional bias, so a reversal stays possible."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_OPEN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=61.0,
    )
    payload = decision.as_dict()
    assert payload["cancel_remaining_only"] is True
    for key in payload:
        assert "direction" not in key
        assert "side" not in key


# --------------------------------------------------- scope / position orders


def test_position_reduce_order_is_out_of_scope():
    """Position orders keep their own 900s policy - never the 60s entry TTL."""
    decision = evaluate_entry_ttl(
        fact=reconcile_order(
            order=_Order(status=OrderStatus.PARTIALLY_FILLED, filled="300"),
            purpose=ORDER_PURPOSE_POSITION_REDUCE,
            broker_order=_Order(status=OrderStatus.PARTIALLY_FILLED, filled="300"),
        ),
        durable_status=OrderStatus.PARTIALLY_FILLED.value,
        resting_age=200.0,
    )
    assert decision.action == ACTION_NOT_APPLICABLE
    assert decision.should_cancel is False


def test_position_exit_order_is_out_of_scope():
    decision = evaluate_entry_ttl(
        fact=reconcile_order(
            order=_Order(status=OrderStatus.OPEN),
            purpose=ORDER_PURPOSE_POSITION_EXIT,
            broker_order=_Order(status=OrderStatus.OPEN),
        ),
        durable_status=OrderStatus.OPEN.value,
        resting_age=5000.0,
    )
    assert decision.action == ACTION_NOT_APPLICABLE
    assert decision.should_cancel is False


def test_position_policy_threshold_is_unchanged():
    """§4: the 900s position policy must not be swept into the entry rule."""
    from crypto_trader.order.manager import DEFAULT_STALE_POSITION_ACTION_SECONDS

    assert DEFAULT_STALE_POSITION_ACTION_SECONDS == 900.0
    assert SHORT_TERM_ENTRY_TTL_SECONDS == 60.0


# ---------------------------------------------------- resting age sourcing


def test_resting_age_prefers_opened_then_acknowledged():
    """§5: never the LLM decision time - the factual resting start."""
    opened = NOW - timedelta(seconds=90)
    acknowledged = NOW - timedelta(seconds=120)
    created = NOW - timedelta(seconds=600)
    assert resting_age_seconds(
        opened_at=opened, acknowledged_at=acknowledged, created_at=created, now=NOW
    ) == 90.0
    assert resting_age_seconds(
        opened_at=None, acknowledged_at=acknowledged, created_at=created, now=NOW
    ) == 120.0
    assert resting_age_seconds(
        opened_at=None, acknowledged_at=None, created_at=created, now=NOW
    ) == 600.0


def test_resting_age_is_none_without_any_timestamp():
    assert (
        resting_age_seconds(
            opened_at=None, acknowledged_at=None, created_at=None, now=NOW
        )
        is None
    )


def test_unknown_resting_age_never_expires():
    """An order we cannot time must not be cancelled as if it were old."""
    decision = evaluate_entry_ttl(
        fact=_fact(state=RECON_CONFIRMED_OPEN),
        durable_status=OrderStatus.OPEN.value,
        resting_age=None,
    )
    assert decision.action == ACTION_HOLD
    assert decision.reason == "RESTING_AGE_UNKNOWN"
    assert decision.should_cancel is False


# ------------------------------------------------------ SOPHUSDT shape


def test_SOPHUSDT_shape_enters_entry_liveness_and_expires():
    """Historical shape: live_llm ENTRY, 0/3000, age >> 60s.

    Previously this order was structurally invisible (strategy_id filter) and
    rested for 278 minutes. It must now be classified ENTRY, reconciled, and
    expire through cancel-remaining-only.
    """
    order = _Order(
        status=OrderStatus.OPEN,
        quantity="3000",
        filled="0",
        symbol="SOPHUSDT",
        side=OrderSide.SELL,
        strategy_id="live_llm",
    )
    purpose = classify_order_purpose(
        strategy_id="live_llm", reduce_only=False, trade_plan_state="APPROVED"
    )
    assert purpose == ORDER_PURPOSE_ENTRY
    assert entry_liveness_eligible(
        purpose=purpose, durable_status=OrderStatus.OPEN.value
    ) is True

    fact = reconcile_order(
        order=order,
        purpose=purpose,
        broker_order=_Order(status=OrderStatus.OPEN, quantity="3000", filled="0"),
    )
    assert fact.state == RECON_CONFIRMED_OPEN

    decision = evaluate_entry_ttl(
        fact=fact,
        durable_status=OrderStatus.OPEN.value,
        resting_age=278 * 60.0,
    )
    assert decision.should_cancel is True
    assert decision.cancel_remaining_only is True
    assert Decimal(decision.remaining_quantity) == Decimal("3000")


def test_ETHFI_shape_position_review_still_reaches_chief():
    """Historical shape: open position + general pool spent -> review still runs."""
    from crypto_trader.llm_chief.budget import (
        P1_POSITION_LIFECYCLE,
        P2_FINAL_ENTRY_DECISION,
        P3_SELECTED_SYMBOL_RESEARCH,
        BudgetConfig,
        GlobalLLMBudget,
    )
    from crypto_trader.llm_chief.context import ChiefTraderContext
    from crypto_trader.llm_chief.decision import PositionState
    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=120))
    for priority in (P2_FINAL_ENTRY_DECISION, P3_SELECTED_SYMBOL_RESEARCH):
        while budget.try_acquire(priority, operation="general").granted:
            pass

    engine = ChiefTraderEngine(provider=object(), budget=budget)
    ctx = ChiefTraderContext(
        symbol="ETHFIUSDT",
        market_snapshot={},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        position_state=PositionState.OPEN,
        prepared_at="2026-01-01T00:00:00+00:00",
    )
    ticket = budget.try_acquire(
        engine.purpose_priority(ctx), operation="tool_selection"
    )
    assert ticket.granted is True
    assert ticket.priority == P1_POSITION_LIFECYCLE


# ------------------------------------------------------------ performance


def _executable_source(module) -> str:
    """Source with docstrings stripped, so prose cannot satisfy an assertion."""
    import ast as _ast
    import inspect

    tree = _ast.parse(inspect.getsource(module))
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], _ast.Expr) and isinstance(
                body[0].value, _ast.Constant
            ) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [_ast.Pass()]
    return _ast.unparse(tree)


def test_ttl_does_not_use_a_second_timer_or_async_task():
    """§43: TTL rides the existing reconciliation cadence - no new loop."""
    from crypto_trader.order import entry_ttl as module

    code = _executable_source(module)
    for forbidden in (
        "asyncio.create_task",
        "asyncio.sleep",
        "threading.Timer",
        "while True",
    ):
        assert forbidden not in code, f"TTL introduced its own scheduler: {forbidden}"


def test_ttl_makes_no_llm_calls():
    """§19/§43: enforcing a lifetime is not a new trading decision."""
    from crypto_trader.order import entry_ttl as module

    code = _executable_source(module).lower()
    for forbidden in ("complete_json", "provider", "try_acquire", "deepseek"):
        assert forbidden not in code, f"TTL reached the LLM: {forbidden}"
