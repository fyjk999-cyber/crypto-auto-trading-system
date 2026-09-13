"""F4: formal ORDER reconciliation (O1-O7) + F5 purpose classification.

The runtime had balances and positions reconciliation but NO order
reconciliation, so a resting order could sit for hours (live evidence: a
``live_llm`` entry rested OPEN, 0/3000 filled, for 278 minutes) with nobody able
to state as a fact whether the broker still held it.

The invariant under test is that reconciliation REPORTS and never guesses:
a missing or ambiguous broker view is UNKNOWN/MISSING, never CANCELLED/FAILED.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide, OrderStatus
from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_OTHER,
    ORDER_PURPOSE_POSITION_EXIT,
    ORDER_PURPOSE_POSITION_REDUCE,
    RECON_CONFIRMED_CANCELLED,
    RECON_CONFIRMED_FILLED,
    RECON_CONFIRMED_OPEN,
    RECON_CONFIRMED_PARTIALLY_FILLED,
    RECON_CONFIRMED_REJECTED,
    RECON_MISSING,
    RECON_UNKNOWN,
    classify_order_purpose,
    reconcile_order,
)


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
        order_id="ord_1",
    ):
        self.internal_order_id = order_id
        self.client_order_id = "cid_1"
        self.exchange_order_id = exchange_order_id
        self.symbol = symbol
        self.side = side
        self.status = status
        self.quantity = Decimal(quantity)
        self.filled_quantity = Decimal(filled)


def _broker(status=OrderStatus.OPEN, filled="0", exchange_order_id="sim_1", symbol="SOPHUSDT",
            side=OrderSide.SELL):
    return _Order(
        status=status,
        filled=filled,
        exchange_order_id=exchange_order_id,
        symbol=symbol,
        side=side,
    )


# ------------------------------------------------------------------- O1-O6


def test_O1_db_open_broker_open_is_confirmed_open():
    fact = reconcile_order(
        order=_Order(), purpose=ORDER_PURPOSE_ENTRY, broker_order=_broker()
    )
    assert fact.state == RECON_CONFIRMED_OPEN
    assert fact.identity_confirmed is True
    assert fact.is_live is True


def test_O2_db_open_broker_filled_absorbs_the_factual_fill():
    fact = reconcile_order(
        order=_Order(filled="0"),
        purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(status=OrderStatus.FILLED, filled="1000"),
    )
    assert fact.state == RECON_CONFIRMED_FILLED
    assert Decimal(fact.filled_quantity) == Decimal("1000")
    assert Decimal(fact.remaining_quantity) == Decimal("0")
    assert fact.is_terminal is True


def test_O2b_factual_fills_are_never_rolled_back():
    """A larger broker fill wins; a larger DURABLE fill is never discarded."""
    fact = reconcile_order(
        order=_Order(filled="400"),
        purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(status=OrderStatus.PARTIALLY_FILLED, filled="300"),
    )
    assert Decimal(fact.filled_quantity) == Decimal("400")
    assert Decimal(fact.remaining_quantity) == Decimal("600")


def test_O3_db_open_broker_cancelled_is_terminal_cancellation():
    fact = reconcile_order(
        order=_Order(), purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(status=OrderStatus.CANCELLED),
    )
    assert fact.state == RECON_CONFIRMED_CANCELLED
    assert fact.is_terminal is True


def test_O3b_broker_rejected_is_terminal_rejection():
    fact = reconcile_order(
        order=_Order(), purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(status=OrderStatus.REJECTED),
    )
    assert fact.state == RECON_CONFIRMED_REJECTED


def test_O4_db_open_broker_unknown_stays_unknown_not_failed():
    """The core invariant: an ambiguous view must never become a terminal one."""
    fact = reconcile_order(
        order=_Order(status=OrderStatus.UNKNOWN), purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(status=OrderStatus.UNKNOWN),
    )
    assert fact.state == RECON_UNKNOWN
    assert fact.is_unknown is True
    assert fact.state not in (RECON_CONFIRMED_FILLED, RECON_CONFIRMED_CANCELLED,
                              RECON_CONFIRMED_REJECTED)


def test_O4b_broker_provider_error_is_unknown_not_missing():
    fact = reconcile_order(
        order=_Order(), purpose=ORDER_PURPOSE_ENTRY,
        broker_error=TimeoutError("provider down"),
    )
    assert fact.state == RECON_UNKNOWN
    assert "BROKER_OBSERVATION_FAILED" in fact.reason


def test_O4c_identity_mismatch_is_unknown():
    """A record that cannot be proven to be THIS order proves nothing."""
    fact = reconcile_order(
        order=_Order(exchange_order_id="sim_A"),
        purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(exchange_order_id="sim_B"),
    )
    assert fact.state == RECON_UNKNOWN
    assert fact.identity_confirmed is False
    assert fact.reason == "ORDER_IDENTITY_UNCONFIRMED"


def test_O4d_symbol_mismatch_is_unknown():
    fact = reconcile_order(
        order=_Order(symbol="SOPHUSDT"),
        purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(symbol="OTHERUSDT"),
    )
    assert fact.state == RECON_UNKNOWN


def test_O4e_side_mismatch_is_unknown():
    fact = reconcile_order(
        order=_Order(side=OrderSide.SELL),
        purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(side=OrderSide.BUY),
    )
    assert fact.state == RECON_UNKNOWN


# ------------------------------------------------------------------- O5/O7


def test_O5_partial_fill_lineage_is_consistent():
    fact = reconcile_order(
        order=_Order(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300"),
        purpose=ORDER_PURPOSE_ENTRY,
        broker_order=_broker(status=OrderStatus.PARTIALLY_FILLED, filled="300"),
    )
    assert fact.state == RECON_CONFIRMED_PARTIALLY_FILLED
    assert Decimal(fact.filled_quantity) == Decimal("300")
    assert Decimal(fact.remaining_quantity) == Decimal("700")


def test_O6_repeated_reconciliation_is_stable():
    """Reconciling N times with the same facts yields the same verdict."""
    order = _Order(status=OrderStatus.PARTIALLY_FILLED, filled="300")
    broker = _broker(status=OrderStatus.PARTIALLY_FILLED, filled="300")
    states = {
        reconcile_order(order=order, purpose=ORDER_PURPOSE_ENTRY, broker_order=broker).state
        for _ in range(10)
    }
    assert states == {RECON_CONFIRMED_PARTIALLY_FILLED}


def test_O7_restart_without_broker_memory_is_not_terminal():
    """DB OPEN + no in-process broker record must NOT become a terminal verdict.

    PAPER keeps part of the open-order state in memory, so an absent record
    proves nothing; treating it as failure is what enables blind resubmission.
    """
    fact = reconcile_order(order=_Order(), purpose=ORDER_PURPOSE_ENTRY, broker_order=None)
    assert fact.state == RECON_MISSING
    assert fact.is_terminal is False, "MISSING must never masquerade as terminal"
    assert fact.is_unknown is True
    assert fact.reason == "BROKER_RECORD_ABSENT"


def test_reconciliation_fact_is_self_describing():
    fact = reconcile_order(
        order=_Order(), purpose=ORDER_PURPOSE_ENTRY, broker_order=_broker()
    )
    payload = fact.as_dict()
    for key in (
        "order_id",
        "symbol",
        "purpose",
        "state",
        "durable_status",
        "broker_status",
        "identity_confirmed",
        "filled_quantity",
        "remaining_quantity",
        "last_broker_observation_at",
        "reason",
    ):
        assert key in payload, f"reconciliation fact lost {key}"


# ------------------------------------------------------- F5 purpose classification


def test_purpose_entry_for_a_live_llm_plan_order():
    """The SOPHUSDT shape: live_llm + plan relationship => ENTRY."""
    assert (
        classify_order_purpose(
            strategy_id="live_llm", reduce_only=False, trade_plan_state="APPROVED"
        )
        == ORDER_PURPOSE_ENTRY
    )


def test_purpose_position_reduce_from_reduce_only_intent():
    assert (
        classify_order_purpose(strategy_id="live_llm", reduce_only=True)
        == ORDER_PURPOSE_POSITION_REDUCE
    )


def test_purpose_position_exit_from_reduce_only_exit_intent():
    assert (
        classify_order_purpose(
            strategy_id="live_llm", reduce_only=True, direction="EXIT"
        )
        == ORDER_PURPOSE_POSITION_EXIT
    )


def test_purpose_position_orders_by_strategy_id_fallback():
    assert (
        classify_order_purpose(strategy_id="live_llm_position")
        == ORDER_PURPOSE_POSITION_REDUCE
    )


def test_purpose_other_for_unknown_shape():
    assert classify_order_purpose(strategy_id=None) == ORDER_PURPOSE_OTHER


def test_purpose_is_not_decided_by_strategy_id_alone():
    """Classification must consult intent, not only the strategy string."""
    import inspect

    from crypto_trader.order import reconciliation as module

    source = inspect.getsource(module.classify_order_purpose)
    assert "reduce_only" in source
    assert "trade_plan_state" in source
    assert "POSITION_STRATEGY_IDS" in source
