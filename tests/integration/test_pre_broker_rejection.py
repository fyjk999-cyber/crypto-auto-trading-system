"""F6.2: pre-broker rejection recovery (incident ord_4b4d845c...).

The incident
------------
A position-reducing order on an OPEN position was refused by the PAPER adapter
before the broker was ever called ("no factual book"), but it was recorded as
UNKNOWN rather than REJECTED:

    except UnknownExecutionState: ...
    except (TemporaryNetworkError, RateLimited, ExchangeError): mark_unknown(...)
    except OrderRejected: reject(...)          # UNREACHABLE

``OrderRejected`` subclasses ``ExchangeError``, so the broad clause swallowed it
and the specific clause was dead code. Because the pending-position-action guard
treats UNKNOWN as still pending, the plan's REDUCE/EXIT path stayed blocked with
nothing left able to resolve it - a permanent position-management deadlock on a
live position.

The fix has two halves, and BOTH are required:
  1. reachability: order the clauses so OrderRejected is handled first;
  2. repairability: a narrow classifier that terminalises a historical UNKNOWN
     only with POSITIVE proof the broker was never reached.

``exchange_order_id IS NULL`` alone is explicitly NOT sufficient: on a real
timeout the order may have reached the exchange before the id was persisted, and
treating that as rejected is how a live position gets silently abandoned.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from crypto_trader.domain.errors import (
    ExchangeError,
    OrderRejected,
    RateLimited,
    TemporaryNetworkError,
    UnknownExecutionState,
)
from crypto_trader.domain.models import Order
from crypto_trader.order.pre_broker_rejection import (
    CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED,
    CLASSIFICATION_REMAINS_UNKNOWN,
    PRE_BROKER_REJECTION_REASONS,
    REASON_MARKET_DATA_SYMBOL_MISMATCH,
    REASON_MARKET_DATA_UNAVAILABLE,
    TERMINAL_REASON_PREFIX,
    classify_pre_broker_rejection,
    extract_pre_broker_reason,
    repair_pre_broker_rejections,
)

INCIDENT_ORDER_ID = "ord_4b4d845cf27d433dab72567f1bf77328"


# ------------------------------------------------------- §19 exception hierarchy


def test_ORDER_REJECTED_IS_EXCHANGE_ERROR():
    assert issubclass(OrderRejected, ExchangeError) is True


def test_ORDER_REJECTED_BRANCH_PRECEDES_EXCHANGE_ERROR_BRANCH():
    """The dead-clause bug must not come back.

    Asserted on the real source order, because this is exactly the property that
    was silently false for the whole life of the running build.
    """
    import inspect
    import re

    from crypto_trader.runtime.engine import TradingEngine

    source = inspect.getsource(TradingEngine.process_signal)
    clauses = [m for m in re.finditer(r"except\s+([^:]+):", source)]
    names = [
        ("OrderRejected" if "OrderRejected" in c.group(1) else
         "ExchangeError" if "ExchangeError" in c.group(1) else
         "UnknownExecutionState" if "UnknownExecutionState" in c.group(1) else None)
        for c in clauses
    ]
    names = [n for n in names if n]
    assert "OrderRejected" in names and "ExchangeError" in names, names
    assert names.index("OrderRejected") < names.index("ExchangeError"), (
        "OrderRejected must be caught before ExchangeError or it stays dead code"
    )
    assert names.index("UnknownExecutionState") < names.index("ExchangeError")


def test_market_data_reasons_are_declared_pre_broker():
    """Each repairable reason must be justified by adapter source order."""
    from crypto_trader.order.pre_broker_rejection import PRE_BROKER_RAISE_SITES

    for reason in PRE_BROKER_REJECTION_REASONS:
        assert reason in PRE_BROKER_RAISE_SITES, reason


def test_market_data_guard_raises_before_super_submit():
    """§5: the adapter raises these BEFORE it calls the broker."""
    source = pathlib.Path(
        "src/crypto_trader/simulator/real_market_paper.py"
    ).read_text()
    body = source[source.index("async def submit_order") :]
    super_call = body.index("return await super().submit_order(order)")
    for reason in PRE_BROKER_REJECTION_REASONS:
        assert body.index(f'OrderRejected("{reason}")') < super_call, (
            f"{reason} is raised after the broker call, so it is not pre-broker"
        )


# --------------------------------------------------- §24/§25 classifier


def test_HISTORICAL_REPAIR_POSITIVE():
    verdict = classify_pre_broker_rejection(
        status="UNKNOWN",
        exchange_order_id=None,
        filled_quantity=0,
        durable_fill_count=0,
        failure_reason=REASON_MARKET_DATA_UNAVAILABLE,
        audit_lineage_proves_pre_broker=True,
    )
    assert verdict.classification == CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED
    assert verdict.repair_allowed is True
    assert verdict.terminal_reason == f"{TERMINAL_REASON_PREFIX}:{REASON_MARKET_DATA_UNAVAILABLE}"


def test_HISTORICAL_REPAIR_POSITIVE_symbol_mismatch():
    verdict = classify_pre_broker_rejection(
        status="UNKNOWN",
        exchange_order_id=None,
        filled_quantity=0,
        durable_fill_count=0,
        failure_reason=REASON_MARKET_DATA_SYMBOL_MISMATCH,
        audit_lineage_proves_pre_broker=True,
    )
    assert verdict.repair_allowed is True


@pytest.mark.parametrize(
    "kwargs,expected_reason",
    [
        ({"filled_quantity": 1}, "FILLED_QUANTITY_NONZERO"),
        ({"durable_fill_count": 1}, "DURABLE_FILL_PRESENT"),
        ({"exchange_order_id": "sim_abc"}, "BROKER_ID_PRESENT"),
        ({"failure_reason": "TIMEOUT"}, "FAILURE_REASON_NOT_PRE_BROKER:TIMEOUT"),
        ({"failure_reason": None}, "FAILURE_REASON_MISSING"),
        ({"audit_lineage_proves_pre_broker": False}, "PRE_BROKER_LINEAGE_UNPROVEN"),
        ({"status": "OPEN"}, "STATUS_NOT_UNKNOWN"),
        ({"filled_quantity": "not-a-number"}, "FILLED_QUANTITY_UNPARSEABLE"),
    ],
)
def test_HISTORICAL_REPAIR_NEGATIVE(kwargs, expected_reason):
    """§25: any doubt keeps the order UNKNOWN."""
    base = {
        "status": "UNKNOWN",
        "exchange_order_id": None,
        "filled_quantity": 0,
        "durable_fill_count": 0,
        "failure_reason": REASON_MARKET_DATA_UNAVAILABLE,
        "audit_lineage_proves_pre_broker": True,
    }
    base.update(kwargs)
    verdict = classify_pre_broker_rejection(**base)
    assert verdict.classification == CLASSIFICATION_REMAINS_UNKNOWN
    assert verdict.repair_allowed is False
    assert verdict.reason == expected_reason


# ------------------------------------------------- §13 generic errors stay UNKNOWN


def test_GENERIC_NETWORK_ERROR_REMAINS_UNKNOWN():
    """A transient/ambiguous failure must never be forced to REJECTED."""
    for exc in (TemporaryNetworkError("t"), RateLimited("r"), ExchangeError("e")):
        verdict = classify_pre_broker_rejection(
            status="UNKNOWN",
            exchange_order_id=None,
            filled_quantity=0,
            durable_fill_count=0,
            failure_reason=type(exc).__name__,
            audit_lineage_proves_pre_broker=False,
        )
        assert verdict.repair_allowed is False, type(exc).__name__


def test_UNKNOWN_EXECUTION_STATE_STAYS_UNKNOWN():
    """§12: a true timeout must keep its broker-query path."""
    assert issubclass(UnknownExecutionState, ExchangeError)
    verdict = classify_pre_broker_rejection(
        status="UNKNOWN",
        exchange_order_id=None,
        filled_quantity=0,
        durable_fill_count=0,
        failure_reason="UnknownExecutionState",
        audit_lineage_proves_pre_broker=False,
    )
    assert verdict.repair_allowed is False


# ---------------------------------------------------- §14 lineage extraction


class _Event:
    def __init__(self, event_type, payload):
        self.event_type = event_type
        self.payload = payload


def test_lineage_proven_by_explicit_broker_reached_false():
    events = [
        _Event(
            "ORDER_REJECTED",
            {"reason": REASON_MARKET_DATA_UNAVAILABLE, "broker_reached": False},
        )
    ]
    reason, proven = extract_pre_broker_reason(events)
    assert reason == REASON_MARKET_DATA_UNAVAILABLE
    assert proven is True


def test_lineage_proven_by_unknown_event_naming_a_pre_broker_reason():
    events = [_Event("ORDER_UNKNOWN", {"reason": REASON_MARKET_DATA_UNAVAILABLE})]
    reason, proven = extract_pre_broker_reason(events)
    assert reason == REASON_MARKET_DATA_UNAVAILABLE
    assert proven is True


def test_lineage_not_proven_for_ambiguous_reason():
    events = [_Event("ORDER_UNKNOWN", {"reason": "SOCKET_TIMEOUT"})]
    reason, proven = extract_pre_broker_reason(events)
    assert reason is None
    assert proven is False


def test_lineage_not_proven_without_events():
    reason, proven = extract_pre_broker_reason([])
    assert reason is None and proven is False


def test_RECOVERYSERVICE_lookup_key_includes_client_order_id():
    """§14: exchange_id=None with a client_id is NOT a missing order id."""
    source = pathlib.Path("src/crypto_trader/runtime/recovery.py").read_text()
    assert "client_order_id" in source
    assert "exchange_order_id" in source


# ------------------------------------------------------- §9 incident fixture


def _incident_order():
    now = datetime.now(UTC)
    return Order(
        internal_order_id=INCIDENT_ORDER_ID,
        client_order_id="live_llm_position_position_decision_c307943e06494f13b8db6a3e",
        exchange_order_id=None,
        symbol="IOSTUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=Decimal("0.0008848"),
        quantity=Decimal("15"),
        filled_quantity=Decimal("0"),
        status=OrderStatus.UNKNOWN,
        strategy_id="live_llm_position",
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
        metadata={
            "trade_plan_id": "plan_ca0660c80a154bfc88f2415f0e6bf258",
            "decision_id": "llm_72d5368f11764cdc98940dd63aa0d337",
            "lifecycle_action": "REDUCE",
            "reduce_only": True,
        },
    )


@pytest.mark.asyncio
async def test_INCIDENT_SHAPE_is_repaired_to_REJECTED():
    order = _incident_order()
    terminalized: list = []

    async def _fill_count(_):
        return 0

    async def _events(_):
        return [_Event("ORDER_UNKNOWN", {"reason": REASON_MARKET_DATA_UNAVAILABLE})]

    async def _terminalize(target, reason):
        terminalized.append((target.internal_order_id, reason))

    report = await repair_pre_broker_rejections(
        order_manager=None,
        unresolved_orders=[order],
        fill_counter=_fill_count,
        event_loader=_events,
        terminalize=_terminalize,
    )
    assert report.counts() == {CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED: 1}
    assert terminalized == [
        (INCIDENT_ORDER_ID, f"{TERMINAL_REASON_PREFIX}:{REASON_MARKET_DATA_UNAVAILABLE}")
    ]


@pytest.mark.asyncio
async def test_INCIDENT_REPAIR_creates_no_broker_fact():
    """§8: no exchange id, no cancel, no fill, no acknowledgement."""
    order = _incident_order()
    calls: list = []

    async def _fill_count(_):
        return 0

    async def _events(_):
        return [_Event("ORDER_UNKNOWN", {"reason": REASON_MARKET_DATA_UNAVAILABLE})]

    async def _terminalize(target, reason):
        calls.append(("terminalize", reason))
        # Only a status transition may be requested.
        assert target.exchange_order_id is None

    await repair_pre_broker_rejections(
        order_manager=None,
        unresolved_orders=[order],
        fill_counter=_fill_count,
        event_loader=_events,
        terminalize=_terminalize,
    )
    assert [c[0] for c in calls] == ["terminalize"]
    assert order.filled_quantity == Decimal("0")
    assert order.exchange_order_id is None


@pytest.mark.asyncio
async def test_incident_skipped_when_a_fill_exists():
    order = _incident_order()

    async def _fill_count(_):
        return 1

    async def _events(_):
        return [_Event("ORDER_UNKNOWN", {"reason": REASON_MARKET_DATA_UNAVAILABLE})]

    async def _terminalize(*_):
        raise AssertionError("must not terminalise an order with a fill")

    report = await repair_pre_broker_rejections(
        order_manager=None,
        unresolved_orders=[order],
        fill_counter=_fill_count,
        event_loader=_events,
        terminalize=_terminalize,
    )
    assert report.repaired == []
    assert report.counts() == {CLASSIFICATION_REMAINS_UNKNOWN: 1}


@pytest.mark.asyncio
async def test_fill_counter_error_is_treated_as_unsafe():
    """An unreadable fill count must not be read as 'no fills'."""
    order = _incident_order()

    async def _fill_count(_):
        raise RuntimeError("db unavailable")

    async def _events(_):
        return [_Event("ORDER_UNKNOWN", {"reason": REASON_MARKET_DATA_UNAVAILABLE})]

    async def _terminalize(*_):
        raise AssertionError("must not terminalise on an unreadable fill count")

    report = await repair_pre_broker_rejections(
        order_manager=None,
        unresolved_orders=[order],
        fill_counter=_fill_count,
        event_loader=_events,
        terminalize=_terminalize,
    )
    assert report.repaired == []


@pytest.mark.asyncio
async def test_non_unknown_orders_are_untouched():
    order = _incident_order()
    order.status = OrderStatus.OPEN
    called = False

    async def _terminalize(*_):
        nonlocal called
        called = True

    await repair_pre_broker_rejections(
        order_manager=None,
        unresolved_orders=[order],
        fill_counter=lambda _: _anext(0),
        event_loader=lambda _: _anext([]),
        terminalize=_terminalize,
    )
    assert called is False


async def _anext(value):
    return value


# ------------------------------------------------- §10 pending action unlock


def test_repair_terminalises_so_the_pending_guard_releases():
    """The repaired order is REJECTED, which is NOT a pending position action."""
    verdict = classify_pre_broker_rejection(
        status="UNKNOWN",
        exchange_order_id=None,
        filled_quantity=0,
        durable_fill_count=0,
        failure_reason=REASON_MARKET_DATA_UNAVAILABLE,
        audit_lineage_proves_pre_broker=True,
    )
    assert verdict.repair_allowed is True
    import inspect

    from crypto_trader.order.manager import OrderManager

    source = inspect.getsource(OrderManager.pending_position_action_facts)
    # The guard's pending set is the reason an UNKNOWN order deadlocked the plan
    # while a REJECTED one cannot.
    assert 'OrderStatus.UNKNOWN.value' in source
    assert 'OrderStatus.REJECTED.value' not in source


def _executable_source(path: str) -> str:
    """Source with docstrings stripped, so prose cannot satisfy an assertion."""
    import ast as _ast

    tree = _ast.parse(pathlib.Path(path).read_text())
    for node in _ast.walk(tree):
        if isinstance(
            node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], _ast.Expr)
                and isinstance(body[0].value, _ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [_ast.Pass()]
    return _ast.unparse(tree)


def test_repair_module_creates_no_broker_or_llm_side_effects():
    import ast as _ast

    # Assert on CALLS and ATTRIBUTE ACCESS, not on string literals: the module
    # legitimately names these operations in its justification map.
    tree = _ast.parse(pathlib.Path("src/crypto_trader/order/pre_broker_rejection.py").read_text())
    forbidden = {
        "submit_order",
        "complete_json",
        "try_acquire",
        "apply_fill",
        "acknowledge",
        "cancel_pending",
        "create_task",
    }
    reached: set[str] = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in forbidden:
                reached.add(name)
        elif isinstance(node, _ast.Attribute) and node.attr in forbidden:
            reached.add(node.attr)
    assert not reached, f"repair reached {sorted(reached)}"
