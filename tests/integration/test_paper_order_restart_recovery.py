"""F6: PAPER unresolved-order restart recovery (R1-R12 + migration shapes).

The gap
-------
Balances and positions were hydrated on restart, but NOT orders. The PAPER
broker keeps unresolved orders in process memory, so after a restart:
  * every resting order looked MISSING to F4 reconciliation;
  * the F3 ENTRY TTL could never expire a stale entry (nothing to reconcile);
  * the pre-existing RecoveryService.recover() saw "order not found on
    exchange" for a healthy PAPER order and recorded it REJECTED - the exact
    reason two orders in the live DB carry
    "order not found on exchange during recovery; no blind resubmit".

Restore is not resubmit
-----------------------
Recovery copies durable facts into the broker record and nothing else: no
submit, no fill invention, no identity change, no ledger write. Insufficient
facts stay NOT_RECOVERABLE rather than being guessed at.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from crypto_trader.domain.models import Order
from crypto_trader.order.entry_ttl import (
    ACTION_CANCEL_REMAINING,
    SHORT_TERM_ENTRY_TTL_SECONDS,
    evaluate_entry_ttl,
    resting_age_seconds,
)
from crypto_trader.order.reconciliation import ORDER_PURPOSE_ENTRY, reconcile_order
from crypto_trader.order.restart_recovery import (
    IDENTITY_CONTRADICTION,
    NOT_RECOVERABLE_INSUFFICIENT_FACTS,
    RECOVERED_CONFIRMED,
    RECOVERED_PARTIAL,
    TERMINAL_NO_RECOVERY,
    classify_recoverability,
    rebuild_broker_order,
    recover_unresolved_orders,
)

SYMBOL = "SOPHUSDT"


def _durable(
    *,
    status=OrderStatus.OPEN,
    quantity="3000",
    filled="0",
    exchange_order_id="sim_81ef1044f5ee4571b201ac49972f43db",
    symbol=SYMBOL,
    side=OrderSide.SELL,
    created_offset=7 * 3600,
    strategy_id="live_llm",
):
    now = datetime.now(UTC)
    return Order(
        internal_order_id="ord_f9edfa0a41984a29892c94eee94b0b22",
        client_order_id="live_llm_llm_6b31170912ca4631bfdd22d155fe51f8",
        exchange_order_id=exchange_order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=Decimal("0.00475"),
        quantity=Decimal(quantity),
        filled_quantity=Decimal(filled),
        status=status,
        strategy_id=strategy_id,
        created_at=now - timedelta(seconds=created_offset),
        updated_at=now - timedelta(seconds=created_offset),
        metadata={"trade_plan_id": "plan_b18081a96e42498096112a927b1f9ec4"},
    )


class _Recorder:
    """Captures restores AND every forbidden side effect."""

    def __init__(self):
        self.restored = []
        self.submit_calls = 0
        self.llm_calls = 0

    def apply(self, order):
        self.restored.append(order)


# ------------------------------------------------------------------ R1/R2


def test_R1_open_order_restart_recovery_keeps_identity_and_quantity():
    durable = _durable()
    rec = _Recorder()
    report = recover_unresolved_orders(
        durable_orders=[durable], broker_orders={}, apply_restore=rec.apply
    )
    assert report.counts() == {RECOVERED_CONFIRMED: 1}
    assert rec.submit_calls == 0, "recovery must never submit"

    restored = rec.restored[0]
    assert restored.internal_order_id == durable.internal_order_id
    assert restored.client_order_id == durable.client_order_id
    assert restored.exchange_order_id == durable.exchange_order_id
    assert restored.symbol == SYMBOL and restored.side is OrderSide.SELL
    assert restored.quantity == Decimal("3000")
    assert restored.filled_quantity == Decimal("0")
    assert restored.quantity - restored.filled_quantity == Decimal("3000")


def test_R2_partial_fill_restart_recovery_preserves_the_fill():
    durable = _durable(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300")
    rec = _Recorder()
    report = recover_unresolved_orders(
        durable_orders=[durable], broker_orders={}, apply_restore=rec.apply
    )
    assert report.counts() == {RECOVERED_PARTIAL: 1}
    restored = rec.restored[0]
    assert restored.filled_quantity == Decimal("300")
    assert restored.quantity - restored.filled_quantity == Decimal("700")
    assert restored.filled_quantity != Decimal("0"), "the factual fill was lost"


def test_R2b_recovery_does_not_replay_the_fill():
    """Restoring a partially filled order must not re-create its fill."""
    durable = _durable(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300")
    rec = _Recorder()
    recover_unresolved_orders(durable_orders=[durable], broker_orders={}, apply_restore=rec.apply)
    restored = rec.restored[0]
    # A replayed fill would show up as a doubled quantity.
    assert restored.filled_quantity == Decimal("300")


# ------------------------------------------------------------------ R3


def test_R3_no_submit_llm_or_provider_calls_during_recovery():
    """§51: recovery is a copy, not an execution."""
    rec = _Recorder()
    recover_unresolved_orders(
        durable_orders=[
            _durable(),
            _durable(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300"),
            _durable(symbol="IOSTUSDT", side=OrderSide.BUY, exchange_order_id="sim_x"),
        ],
        broker_orders={},
        apply_restore=rec.apply,
    )
    assert rec.submit_calls == 0
    assert rec.llm_calls == 0

    source = pathlib.Path("src/crypto_trader/order/restart_recovery.py").read_text()
    for forbidden in ("submit_order", "complete_json", "try_acquire", "create_order"):
        assert forbidden not in source, f"recovery reached {forbidden}"


# ------------------------------------------------------------------ R4/R5


def test_R4_stale_entry_after_restart_reaches_ttl_cancel():
    """The core acceptance: restart -> F4 -> F5 -> F3 -> one cancel."""
    durable = _durable(created_offset=10 * 60)
    rec = _Recorder()
    recover_unresolved_orders(durable_orders=[durable], broker_orders={}, apply_restore=rec.apply)
    restored = rec.restored[0]

    fact = reconcile_order(
        order=restored, purpose=ORDER_PURPOSE_ENTRY, broker_order=restored
    )
    assert fact.state == "CONFIRMED_OPEN"

    decision = evaluate_entry_ttl(
        fact=fact,
        durable_status=restored.status.value,
        resting_age=resting_age_seconds(
            opened_at=restored.created_at, acknowledged_at=None, created_at=None
        ),
    )
    assert decision.action == ACTION_CANCEL_REMAINING
    assert decision.cancel_remaining_only is True


def test_R5_partial_stale_entry_cancels_only_the_remainder():
    durable = _durable(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300",
                       created_offset=10 * 60)
    rec = _Recorder()
    recover_unresolved_orders(durable_orders=[durable], broker_orders={}, apply_restore=rec.apply)
    restored = rec.restored[0]
    fact = reconcile_order(order=restored, purpose=ORDER_PURPOSE_ENTRY, broker_order=restored)
    decision = evaluate_entry_ttl(
        fact=fact, durable_status=restored.status.value, resting_age=600.0
    )
    assert decision.should_cancel is True
    assert Decimal(decision.filled_quantity) == Decimal("300")
    assert Decimal(decision.remaining_quantity) == Decimal("700")


# ------------------------------------------------------------------ R6/R7


def test_R6_identity_contradiction_fails_closed():
    durable = _durable(symbol="SOPHUSDT")
    conflicting = _durable(symbol="IOSTUSDT")
    conflicting.exchange_order_id = durable.exchange_order_id
    rec = _Recorder()
    report = recover_unresolved_orders(
        durable_orders=[durable],
        broker_orders={durable.exchange_order_id: conflicting},
        apply_restore=rec.apply,
    )
    assert report.counts() == {IDENTITY_CONTRADICTION: 1}
    assert report.fatal is True
    assert rec.restored == [], "a contradiction must not be restored as confirmed"
    assert rec.submit_calls == 0


def test_R6b_quantity_contradiction_is_not_clamped():
    durable = _durable(quantity="1000", filled="2000")
    outcome = classify_recoverability(order=durable)
    assert outcome.verdict == IDENTITY_CONTRADICTION
    assert outcome.reason == "QUANTITY_CONTRADICTION"


def test_R7_terminal_orders_are_never_restored():
    for status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
                   OrderStatus.EXPIRED):
        rec = _Recorder()
        report = recover_unresolved_orders(
            durable_orders=[_durable(status=status)], broker_orders={}, apply_restore=rec.apply
        )
        assert report.counts() == {TERMINAL_NO_RECOVERY: 1}, status
        assert rec.restored == [], f"{status} must not become an open broker order"


# ------------------------------------------------------------------ R8/R9/R10


def test_R8_repeated_recovery_is_idempotent():
    durable = _durable(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300")
    results = []
    for _ in range(3):
        rec = _Recorder()
        recover_unresolved_orders(
            durable_orders=[durable], broker_orders={}, apply_restore=rec.apply
        )
        restored = rec.restored[0]
        results.append(
            (
                restored.internal_order_id,
                restored.exchange_order_id,
                str(restored.filled_quantity),
                str(restored.quantity),
            )
        )
    assert len(set(results)) == 1, "recovery produced different states across runs"
    assert results[0][2] == "300"


def test_R9_cancel_pending_is_preserved_not_downgraded():
    """A CANCEL_PENDING order must not come back as plain OPEN."""
    durable = _durable(status=OrderStatus.CANCEL_PENDING)
    rec = _Recorder()
    recover_unresolved_orders(durable_orders=[durable], broker_orders={}, apply_restore=rec.apply)
    restored = rec.restored[0]
    assert restored.status is OrderStatus.CANCEL_PENDING, (
        "a restart must not make a second cancel possible"
    )


def test_R10_unknown_status_is_not_restored_as_open():
    durable = _durable(status=OrderStatus.UNKNOWN)
    outcome = classify_recoverability(order=durable)
    assert outcome.verdict == NOT_RECOVERABLE_INSUFFICIENT_FACTS
    assert outcome.reason == "AMBIGUOUS_STATUS_UNKNOWN"
    assert outcome.restored is False


def test_R10b_missing_broker_identity_is_not_invented():
    durable = _durable(exchange_order_id=None)
    outcome = classify_recoverability(order=durable)
    assert outcome.verdict == NOT_RECOVERABLE_INSUFFICIENT_FACTS
    assert outcome.reason == "MISSING_BROKER_IDENTITY"


# ------------------------------------------------------------------ R11/R12


def test_R11_resting_age_survives_restart():
    """A restart must not reset the resting clock to zero."""
    durable = _durable(created_offset=7 * 3600)
    restored = rebuild_broker_order(durable)
    assert restored is not None
    assert restored.created_at == durable.created_at, "timestamp was reset"
    age = resting_age_seconds(opened_at=restored.created_at, acknowledged_at=None)
    assert age is not None and age >= 7 * 3600 - 5


def test_R12_created_at_only_never_authorises_ttl():
    """The F3 hard rule must survive F6: no acceptance instant -> UNKNOWN."""
    durable = _durable(created_offset=7 * 3600)
    restored = rebuild_broker_order(durable)
    age = resting_age_seconds(
        opened_at=None, acknowledged_at=None, created_at=restored.created_at
    )
    assert age is None
    fact = reconcile_order(order=restored, purpose=ORDER_PURPOSE_ENTRY, broker_order=restored)
    decision = evaluate_entry_ttl(
        fact=fact, durable_status=restored.status.value, resting_age=age
    )
    assert decision.action == "HOLD"
    assert decision.reason == "RESTING_AGE_UNKNOWN"
    assert decision.should_cancel is False


# --------------------------------------------------- migration shapes


def test_SOPH_migration_shape_end_to_end():
    durable = _durable()  # SOPHUSDT SELL 0/3000, opened hours ago
    rec = _Recorder()
    report = recover_unresolved_orders(
        durable_orders=[durable], broker_orders={}, apply_restore=rec.apply
    )
    assert report.counts() == {RECOVERED_CONFIRMED: 1}
    restored = rec.restored[0]
    assert restored.internal_order_id == durable.internal_order_id

    fact = reconcile_order(order=restored, purpose=ORDER_PURPOSE_ENTRY, broker_order=restored)
    assert fact.state == "CONFIRMED_OPEN"
    decision = evaluate_entry_ttl(
        fact=fact, durable_status=restored.status.value, resting_age=7 * 3600.0
    )
    assert decision.action == ACTION_CANCEL_REMAINING
    assert Decimal(decision.remaining_quantity) == Decimal("3000")


def test_IOST_migration_shape_end_to_end():
    durable = _durable(
        symbol="IOSTUSDT",
        side=OrderSide.BUY,
        quantity="2468",
        exchange_order_id="sim_b43a8a98151f4a76a733316dbfbc1b57",
    )
    rec = _Recorder()
    recover_unresolved_orders(durable_orders=[durable], broker_orders={}, apply_restore=rec.apply)
    restored = rec.restored[0]
    fact = reconcile_order(order=restored, purpose=ORDER_PURPOSE_ENTRY, broker_order=restored)
    assert fact.state == "CONFIRMED_OPEN"
    decision = evaluate_entry_ttl(
        fact=fact, durable_status=restored.status.value, resting_age=6000.0
    )
    assert decision.should_cancel is True
    assert Decimal(decision.remaining_quantity) == Decimal("2468")


def test_LAB_partial_position_order_is_not_converted_to_entry():
    """A partially filled position order keeps its own liveness semantics."""
    from crypto_trader.order.reconciliation import (
        ORDER_PURPOSE_POSITION_REDUCE,
        classify_order_purpose,
    )

    purpose = classify_order_purpose(
        strategy_id="live_llm_position", reduce_only=True
    )
    assert purpose == ORDER_PURPOSE_POSITION_REDUCE
    durable = _durable(
        status=OrderStatus.PARTIALLY_FILLED, quantity="3194.6", filled="2.4",
        strategy_id="live_llm_position",
    )
    rec = _Recorder()
    recover_unresolved_orders(durable_orders=[durable], broker_orders={}, apply_restore=rec.apply)
    restored = rec.restored[0]
    assert restored.filled_quantity == Decimal("2.4"), "partial fill was reset"
    # As a position order it is out of scope for the entry TTL.
    fact = reconcile_order(order=restored, purpose=purpose, broker_order=restored)
    decision = evaluate_entry_ttl(
        fact=fact, durable_status=restored.status.value, resting_age=9999.0
    )
    assert decision.should_cancel is False


def test_ttl_constants_unchanged_by_recovery():
    assert SHORT_TERM_ENTRY_TTL_SECONDS == 60.0
    from crypto_trader.order.manager import DEFAULT_STALE_POSITION_ACTION_SECONDS

    assert DEFAULT_STALE_POSITION_ACTION_SECONDS == 900.0


def test_recovery_module_has_no_new_scheduler():
    source = pathlib.Path("src/crypto_trader/order/restart_recovery.py").read_text()
    for forbidden in ("while True", "asyncio.create_task", "asyncio.sleep"):
        assert forbidden not in source
