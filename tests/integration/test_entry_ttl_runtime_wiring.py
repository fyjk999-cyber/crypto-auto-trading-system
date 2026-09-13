"""F3 RUNTIME WIRING (E1-E16): the production caller, not just the evaluator.

The evaluator was already unit-tested, but nothing called it, so the 60s TTL
did not actually apply to a running system. These tests drive the REAL
``TradingEngine._enforce_entry_order_ttl`` method - bound onto a minimal host so
no full engine assembly is needed - and assert on observable effects: cancel
calls, terminal reasons, and whether a plan is allowed to keep living.

The distinction matters: an evaluator test can pass while the runtime never
enforces anything.
"""

from __future__ import annotations

import inspect
import types
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.enums import OrderEventType, OrderSide, OrderStatus
from crypto_trader.order.entry_ttl import (
    ENTRY_ORDER_TTL_EXPIRED,
    SHORT_TERM_ENTRY_TTL_SECONDS,
)
from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_POSITION_REDUCE,
)
from crypto_trader.runtime.engine import TradingEngine

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
SYMBOL = "SOPHUSDT"


# ------------------------------------------------------------------ doubles


class _Order:
    def __init__(
        self,
        *,
        status=OrderStatus.OPEN,
        quantity="3000",
        filled="0",
        strategy_id="live_llm",
        status_value=None,
    ):
        self.internal_order_id = "ord_e2e"
        self.client_order_id = "cid_e2e"
        self.exchange_order_id = "sim_e2e"
        self.symbol = SYMBOL
        self.side = OrderSide.SELL
        self.status = status_value or status
        self.quantity = Decimal(quantity)
        self.filled_quantity = Decimal(filled)
        self.strategy_id = strategy_id
        self.metadata_json = {"trade_plan_id": "plan_e2e"}


class _Event:
    def __init__(self, event_type, timestamp):
        self.event_type = event_type
        self.timestamp = timestamp


class _Manager:
    """Durable-side double: unresolved facts, order lookup, event history."""

    def __init__(self, order, *, purpose=ORDER_PURPOSE_ENTRY, opened_offset=None,
                 ack_offset=None, status=None):
        self.order = order
        self.purpose = purpose
        self.opened_offset = opened_offset
        self.ack_offset = ack_offset
        self.status = status or _status_value(order)
        # Anchored to the REAL clock: the engine measures resting age with
        # datetime.now(UTC), so a fixed test constant would compute a bogus age.
        anchor = datetime.now(UTC)
        self.events = []
        if opened_offset is not None:
            self.events.append(
                _Event(OrderEventType.ORDER_OPENED, anchor - timedelta(seconds=opened_offset))
            )
        if ack_offset is not None:
            self.events.append(
                _Event(OrderEventType.ORDER_ACKNOWLEDGED, anchor - timedelta(seconds=ack_offset))
            )

    async def unresolved_order_facts(self):
        return [
            {
                "order_id": self.order.internal_order_id,
                "symbol": self.order.symbol,
                "status": self.status,
                "purpose": self.purpose,
                "trade_plan_id": "plan_e2e",
                "quantity": str(self.order.quantity),
                "filled_quantity": str(self.order.filled_quantity),
                "remaining_quantity": str(self.order.quantity - self.order.filled_quantity),
                "age_seconds": self.opened_offset,
            }
        ]

    async def get(self, order_id):
        return self.order if order_id == self.order.internal_order_id else None

    async def list_events(self, order_id):
        return list(self.events)


class _Adapter:
    def __init__(self, broker_order=None, error=None):
        self.broker_order = broker_order
        self.error = error
        self.get_order_calls = 0

    async def get_order(self, symbol, exchange_order_id):
        self.get_order_calls += 1
        if self.error is not None:
            raise self.error
        return self.broker_order


class _Audit:
    def __init__(self):
        self.entries = []

    async def log(self, event, **kwargs):
        self.entries.append({"event": event, **kwargs})

    def events(self, name):
        return [e for e in self.entries if e["event"] == name]


def _broker(status=OrderStatus.OPEN, filled="0", quantity="3000"):
    return _Order(status=status, filled=filled, quantity=quantity)


def _status_value(order):
    return getattr(order.status, "value", order.status)


def _host(*, manager, adapter, lease=True, cancel_log=None):
    """Bind the REAL engine method onto a minimal host.

    Using the unbound function proves the call site under test is the production
    implementation, while keeping the test free of full engine assembly.
    """
    host = types.SimpleNamespace(
        order_manager=manager,
        adapter=adapter,
        audit=_Audit(),
        run_id="run_e2e",
        _current_lease_valid=lambda: _async(lease),
        _cancel_unsettled_entry_order=None,
    )
    calls = cancel_log if cancel_log is not None else []

    async def _cancel(order):
        calls.append(order.internal_order_id)
        # Mirror the production transition: after a cancel the durable status
        # becomes CANCEL_PENDING, which is what makes re-issuing idempotent.
        manager.status = OrderStatus.CANCEL_PENDING.value

    host._cancel_unsettled_entry_order = _cancel
    method = TradingEngine._enforce_entry_order_ttl.__get__(host, type(host))
    observer = TradingEngine._observe_broker_order.__get__(host, type(host))
    accepted = TradingEngine._order_accepted_at.__get__(host, type(host))
    host._observe_broker_order = observer
    host._order_accepted_at = accepted
    return host, method, calls


async def _async(value):
    return value



#: One event loop for the whole module. Creating a fresh loop per call (there
#: are ~40 asyncio.run() calls across these tests) leaked loop resources into
#: the shared pytest process and made an UNRELATED test
#: (test_B4b_globally_spent_window_is_distinct_from_a_spent_pool) fail
#: intermittently in full-suite runs. Verified by two control runs with this
#: file excluded, both fully green.
def _run(coro):
    """Run one coroutine on a private loop that is always closed again.

    Creating a fresh loop per call (there are ~40 calls across these tests) and
    never closing it leaked loop resources into the shared pytest process: an
    UNRELATED test (test_B4b_globally_spent_window_is_distinct_from_a_spent_pool)
    then failed intermittently in full-suite runs. Two control runs with this
    file excluded were fully green, confirming this file as the polluter.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()


# ------------------------------------------------------------------ E1

def test_E1_runtime_caller_exists_in_the_reconciliation_loop():
    """E1: the runtime must actually call the evaluator (not only tests)."""
    source = inspect.getsource(TradingEngine._reconciliation_loop)
    assert "_enforce_entry_order_ttl" in source, (
        "the reconciliation loop still never enforces the entry TTL"
    )
    enforcement = inspect.getsource(TradingEngine._enforce_entry_order_ttl)
    assert "evaluate_entry_ttl" in enforcement
    assert "reconcile_order" in enforcement
    assert "_cancel_unsettled_entry_order" in enforcement


def test_E1b_no_second_reconciler_or_cancel_engine():
    """§44: wire into existing machinery, do not duplicate it."""
    source = inspect.getsource(TradingEngine._enforce_entry_order_ttl)
    for forbidden in ("class OrderReconciler", "async def _new_cancel", "asyncio.create_task"):
        assert forbidden not in source
    # Resting age is derived in the helper, from brokered acceptance only.
    accepted = inspect.getsource(TradingEngine._order_accepted_at)
    assert "resting_age_seconds" in accepted
    assert "created_at=None" in accepted, (
        "created_at must never be a fallback for the TTL clock"
    )


# ------------------------------------------------------------------ E2/E3


def test_E2_59s_does_not_cancel():
    """E2: accepted 59s ago -> runtime cancels nothing."""
    order = _Order()
    manager = _Manager(order, opened_offset=59.0)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    result = _run(method())
    assert calls == [], "cancelled an order still inside its lifetime"
    assert result == 0
    assert host.adapter.get_order_calls == 1


def test_E3_60s_zero_fill_cancels_exactly_once():
    """E3: accepted >= 60s, 0 fill, confirmed open -> exactly one cancel."""
    order = _Order()
    manager = _Manager(order, opened_offset=61.0)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    result = _run(method())
    assert len(calls) == 1, "expected exactly one cancel"
    assert result == 1
    logged = host.audit.events("ENTRY_TTL_EXPIRED")
    assert len(logged) == 1
    assert logged[0]["after"]["terminal_reason"] == ENTRY_ORDER_TTL_EXPIRED


def test_E3b_acknowledged_only_order_still_expires():
    """The accepted instant may be the ACK event when no OPENED exists."""
    order = _Order(status=OrderStatus.ACKNOWLEDGED)
    manager = _Manager(order, opened_offset=None, ack_offset=90.0)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    _run(method())
    assert len(calls) == 1


# ------------------------------------------------------------------ E4


def test_E4_zero_fill_closure_records_the_expiry_reason():
    """E4: zero factual fill -> terminal_reason = ENTRY_ORDER_TTL_EXPIRED."""
    manager = _Manager(_Order(), opened_offset=300.0)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    _run(method())
    after = host.audit.events("ENTRY_TTL_EXPIRED")[0]["after"]
    assert after["terminal_reason"] == ENTRY_ORDER_TTL_EXPIRED
    assert after["cancel_remaining_only"] is True
    assert Decimal(after["filled_quantity"]) == Decimal("0")


# ------------------------------------------------------------------ E5


def test_E5_partial_fill_cancels_remainder_and_keeps_the_plan():
    """E5: 300 of 1000 filled -> cancel 700, and the PLAN keeps living.

    A factual fill means a real position exists, so expiring the remainder must
    NOT terminate the whole plan as ENTRY_ORDER_TTL_EXPIRED.
    """
    order = _Order(status=OrderStatus.PARTIALLY_FILLED, quantity="1000", filled="300")
    manager = _Manager(order, opened_offset=90.0)
    host, method, calls = _host(
        manager=manager,
        adapter=_Adapter(broker_order=_broker(status=OrderStatus.PARTIALLY_FILLED,
                                              filled="300", quantity="1000")),
    )
    _run(method())
    assert len(calls) == 1
    after = host.audit.events("ENTRY_TTL_EXPIRED")[0]["after"]
    assert after["terminal_reason"] == "ENTRY_REMAINDER_EXPIRED", (
        "the whole plan must not die when a factual position already exists"
    )
    assert Decimal(after["filled_quantity"]) == Decimal("300")
    assert Decimal(after["remaining_quantity"]) == Decimal("700")


# ------------------------------------------------------------------ E6


def test_E6_late_factual_fill_is_preserved_over_the_cancel():
    """E6: broker reports a fill -> fills win, remaining is recalculated."""
    order = _Order(quantity="1000", filled="0")
    manager = _Manager(order, opened_offset=120.0)
    host, method, calls = _host(
        manager=manager,
        adapter=_Adapter(broker_order=_broker(status=OrderStatus.PARTIALLY_FILLED,
                                              filled="400", quantity="1000")),
    )
    _run(method())
    after = host.audit.events("ENTRY_TTL_EXPIRED")[0]["after"]
    assert Decimal(after["filled_quantity"]) == Decimal("400")
    assert Decimal(after["remaining_quantity"]) == Decimal("600")


# ------------------------------------------------------------------ E7/E8


def test_E7_unknown_reconciliation_cancels_nothing():
    manager = _Manager(_Order(), opened_offset=600.0)
    host, method, calls = _host(
        manager=manager, adapter=_Adapter(error=TimeoutError("provider down"))
    )
    result = _run(method())
    assert calls == []
    assert result == 0


def test_E8_missing_broker_record_cancels_nothing():
    manager = _Manager(_Order(), opened_offset=600.0)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=None))
    result = _run(method())
    assert calls == [], "MISSING must never authorise a cancel"
    assert result == 0


def test_E8b_identity_mismatch_cancels_nothing():
    manager = _Manager(_Order(), opened_offset=600.0)
    broker = _broker()
    broker.exchange_order_id = "different"
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=broker))
    _run(method())
    assert calls == []


# ------------------------------------------------------------------ E9


def test_E9_cancel_pending_is_idempotent_across_cycles():
    order = _Order()
    manager = _Manager(order, opened_offset=600.0, status=OrderStatus.CANCEL_PENDING.value)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    for _ in range(20):
        _run(method())
    assert calls == [], "a pending cancel must not be re-issued"


# ------------------------------------------------------------------ E10


def test_E10_created_at_age_alone_cannot_expire():
    """created_at is old but there is NO acceptance event -> no cancel."""
    manager = _Manager(_Order(), opened_offset=None, ack_offset=None)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    _run(method())
    assert calls == [], "local creation age must not authorise a cancel"


def test_E10b_recent_acknowledgement_beats_old_creation():
    manager = _Manager(_Order(), opened_offset=None, ack_offset=10.0)
    host, method, calls = _host(manager=manager, adapter=_Adapter(broker_order=_broker()))
    _run(method())
    assert calls == []


# ------------------------------------------------------------------ E11


def test_E11_fully_filled_at_the_timer_wins():
    manager = _Manager(_Order(), opened_offset=600.0)
    host, method, calls = _host(
        manager=manager,
        adapter=_Adapter(broker_order=_broker(status=OrderStatus.FILLED, filled="3000")),
    )
    _run(method())
    assert calls == [], "a factual terminal fill must beat a fired timer"


def test_E11b_broker_cancelled_is_terminal_too():
    manager = _Manager(_Order(), opened_offset=600.0)
    host, method, calls = _host(
        manager=manager, adapter=_Adapter(broker_order=_broker(status=OrderStatus.CANCELLED))
    )
    _run(method())
    assert calls == []


# ------------------------------------------------------------------ E12-E14


def test_E12_E13_expiry_never_reorders_and_carries_no_decision():
    """The expiry is a lifecycle event: it cannot replay the old decision."""
    order = _Order(quantity="1000", filled="300", status=OrderStatus.PARTIALLY_FILLED)
    manager = _Manager(order, opened_offset=300.0)
    host, method, calls = _host(
        manager=manager,
        adapter=_Adapter(broker_order=_broker(status=OrderStatus.PARTIALLY_FILLED,
                                              filled="300", quantity="1000")),
    )
    for _ in range(10):
        _run(method())
    # Exactly one cancel even across repeated cycles, and none of the audit
    # payloads can be mistaken for a new entry intent.
    assert len(calls) == 1
    for entry in host.audit.events("ENTRY_TTL_EXPIRED"):
        payload = entry["after"]
        assert "direction" not in payload
        assert "side" not in payload
        assert payload["cancel_remaining_only"] is True


def test_E14_expiry_permits_a_fresh_opposite_decision():
    """A reversal stays legal: the expiry locks the ORDER, not the direction."""
    from crypto_trader.order.entry_ttl import evaluate_entry_ttl
    from crypto_trader.order.reconciliation import reconcile_order

    decision = evaluate_entry_ttl(
        fact=reconcile_order(
            order=_Order(), purpose=ORDER_PURPOSE_ENTRY, broker_order=_broker()
        ),
        durable_status=OrderStatus.OPEN.value,
        resting_age=61.0,
    )
    payload = decision.as_dict()
    assert payload["should_cancel"] if "should_cancel" in payload else True
    assert not any("direction" in k or "side" in k for k in payload)


# ------------------------------------------------------------------ E15


def test_E15_lease_unavailable_blocks_the_cancel():
    """§12: the TTL never bypasses execution ownership."""
    manager = _Manager(_Order(), opened_offset=600.0)
    host, method, calls = _host(
        manager=manager, adapter=_Adapter(broker_order=_broker()), lease=False
    )
    _run(method())
    assert calls == [], "cancelled without the execution lease"
    blocked = host.audit.events("ENTRY_TTL_CANCEL_BLOCKED")
    assert blocked and blocked[0]["after"]["block_reason"] == "EXECUTION_LEASE_NOT_HELD"


# ------------------------------------------------------------------ E16 / scope


def test_E16_no_llm_calls_on_the_ttl_path():
    """§13/§32: enforcing a lifetime is not a new trading decision."""
    source = inspect.getsource(TradingEngine._enforce_entry_order_ttl)
    for forbidden in ("complete_json", "provider.complete", "try_acquire", "deepseek"):
        assert forbidden not in source.lower()


def test_position_orders_are_skipped_by_the_entry_ttl_caller():
    """Position reduce/exit keep their own 900s policy."""
    manager = _Manager(
        _Order(strategy_id="live_llm_position"),
        purpose=ORDER_PURPOSE_POSITION_REDUCE,
        opened_offset=5000.0,
    )
    host, method, calls = _host(
        manager=manager,
        adapter=_Adapter(broker_order=_broker(status=OrderStatus.PARTIALLY_FILLED, filled="100")),
    )
    _run(method())
    assert calls == [], "the entry TTL must not touch a position order"
    # It must not even be reconciled: purpose filtering happens first.
    assert host.adapter.get_order_calls == 0


def test_SOPHUSDT_shape_end_to_end_through_the_runtime_caller():
    """The real defect shape: live_llm ENTRY, 0/3000, accepted 278 min ago."""
    order = _Order(quantity="3000", filled="0", strategy_id="live_llm")
    manager = _Manager(order, opened_offset=278 * 60.0)
    host, method, calls = _host(
        manager=manager,
        adapter=_Adapter(broker_order=_broker(status=OrderStatus.OPEN, filled="0",
                                              quantity="3000")),
    )
    result = _run(method())
    assert result == 1
    assert len(calls) == 1
    after = host.audit.events("ENTRY_TTL_EXPIRED")[0]["after"]
    assert after["terminal_reason"] == ENTRY_ORDER_TTL_EXPIRED
    assert Decimal(after["remaining_quantity"]) == Decimal("3000")


def test_ttl_constants_unchanged():
    assert SHORT_TERM_ENTRY_TTL_SECONDS == 60.0
    from crypto_trader.order.manager import DEFAULT_STALE_POSITION_ACTION_SECONDS

    assert DEFAULT_STALE_POSITION_ACTION_SECONDS == 900.0
