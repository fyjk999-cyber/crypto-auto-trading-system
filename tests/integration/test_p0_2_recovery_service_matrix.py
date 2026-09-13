"""P0-2 service-level matrix: the CLASSIFIER alone is not acceptance.

Every case below drives the real ``RecoveryService.recover()`` against a real
durable order and a real OrderManager, because a classifier that is correct in
isolation but not wired into recovery protects nothing.

    ORDER NOT FOUND  !=  ORDER NEVER EXISTED

Only a positive pre-broker proof may terminalise. Nothing resubmits.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce, TradingMode
from crypto_trader.domain.errors import (
    OrderNotFound,
    TemporaryNetworkError,
)
from crypto_trader.domain.models import OrderIntent
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.models import FillORM
from crypto_trader.runtime.recovery import RecoveryService

SYMBOL = "BTCUSDT"


class _Adapter:
    """Records every lookup and refuses to be a resubmit target."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.get_order_calls = 0
        self.submit_calls = 0

    async def get_order(self, symbol, exchange_order_id):
        self.get_order_calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def submit_order(self, order):  # pragma: no cover - must never be hit
        self.submit_calls += 1
        raise AssertionError("recovery must never resubmit")


async def _make_order(mgr, *, ack_id: str | None, client="c_p02"):
    intent = OrderIntent(
        client_order_id=client,
        symbol=SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="100",
        quantity="1",
    )
    order = await mgr.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    if ack_id:
        await mgr.ack(order.internal_order_id, ack_id)
    return order


# --------------------------------------------------------------- E: wiring (§2)


@pytest.mark.asyncio
async def test_RECOVERY_E_lookup_failure_stays_unresolved(database):
    """adapter.get_order raising a transport error must NOT terminalise."""
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id=None)
    await mgr.mark_unknown(order.internal_order_id, "TRANSPORT_AMBIGUOUS")

    adapter = _Adapter(TemporaryNetworkError("provider unavailable"))
    service = RecoveryService(mgr, adapter)
    await service.recover("run_e")

    restored = await mgr.get(order.internal_order_id)
    assert restored.status != OrderStatus.REJECTED, (
        "a lookup failure is not evidence about existence"
    )
    assert adapter.submit_calls == 0, "recovery resubmitted"
    assert order.internal_order_id in service.health_unresolved, (
        "an unresolved order must be reported, not silently terminalised"
    )


# ------------------------------------------- A: proven pre-broker (§5)


@pytest.mark.asyncio
async def test_RECOVERY_A_proven_pre_broker_is_rejected(database):
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id=None)
    # Durable ORDER_UNKNOWN carrying a proven pre-broker reason. No broker id,
    # zero fills -> this is the ONE case that may terminalise.
    await mgr.mark_unknown(order.internal_order_id, "MARKET_DATA_UNAVAILABLE")

    adapter = _Adapter(OrderNotFound("sim_missing"))
    service = RecoveryService(mgr, adapter)
    await service.recover("run_a")

    restored = await mgr.get(order.internal_order_id)
    assert restored.status == OrderStatus.REJECTED, (
        f"proven pre-broker refusal must terminalise, got {restored.status}"
    )
    assert adapter.submit_calls == 0


@pytest.mark.asyncio
async def test_RECOVERY_B_ambiguous_reason_stays_unknown(database):
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id=None)
    await mgr.mark_unknown(order.internal_order_id, "TIMEOUT")

    adapter = _Adapter(OrderNotFound("sim_missing"))
    service = RecoveryService(mgr, adapter)
    await service.recover("run_b")

    restored = await mgr.get(order.internal_order_id)
    assert restored.status != OrderStatus.REJECTED
    assert adapter.submit_calls == 0


# ------------------------------------------- C: broker id present (§6)


@pytest.mark.asyncio
async def test_RECOVERY_C_broker_id_present_missing_is_not_rejected(database):
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id="sim_present")
    await mgr.mark_unknown(order.internal_order_id, "TIMEOUT")

    adapter = _Adapter(OrderNotFound("sim_present"))
    service = RecoveryService(mgr, adapter)
    await service.recover("run_c")

    restored = await mgr.get(order.internal_order_id)
    assert restored.status != OrderStatus.REJECTED, (
        "an order WITH a broker id must not be rejected because the venue "
        "could not find it"
    )
    assert order.internal_order_id in service.health_unresolved
    assert adapter.submit_calls == 0


# ------------------------------------------- D: durable fill wins (§7)


@pytest.mark.asyncio
async def test_RECOVERY_D_durable_fill_is_preserved(database):
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id="sim_filled")
    # Order first reaches UNKNOWN (a lookup/transport ambiguity), and only THEN
    # does the factual fill become durable - the exact interleaving recovery must
    # survive. The fill row is inserted directly: this test is about recovery's
    # DECISION, and apply_fill would move the order out of UNKNOWN by itself.
    await mgr.mark_unknown(order.internal_order_id, "TIMEOUT")
    async with database.session_factory() as session:
        session.add(
            FillORM(
                fill_id="fill_p02_d",
                order_id=order.internal_order_id,
                client_order_id=order.client_order_id,
                exchange_order_id=order.exchange_order_id,
                symbol=SYMBOL,
                side=OrderSide.BUY.value,
                price=Decimal("100"),
                quantity=Decimal("1"),
                fee=Decimal("0"),
                timestamp=order.created_at,
            )
        )
        await session.commit()

    async with database.session_factory() as session:
        fills_before = (await session.execute(select(FillORM))).scalars().all()
    assert len(list(fills_before)) == 1

    adapter = _Adapter(OrderNotFound("sim_filled"))
    service = RecoveryService(mgr, adapter)
    await service.recover("run_d")

    restored = await mgr.get(order.internal_order_id)
    assert restored.status != OrderStatus.REJECTED, (
        "a durable fill outranks a not-found answer"
    )
    async with database.session_factory() as session:
        fills_after = (await session.execute(select(FillORM))).scalars().all()
    assert [f.fill_id for f in fills_after] == ["fill_p02_d"], (
        "the factual fill must be preserved, not duplicated or removed"
    )
    assert adapter.submit_calls == 0


# ------------------------------------------------ §4 lineage negative matrix


@pytest.mark.asyncio
async def test_lineage_rejects_unrelated_event_type(database):
    """A same-reason event of an unrelated type is NOT proof.

    This is the exact guard: the reason text alone used to be sufficient, so a
    CANCEL_PENDING carrying "MARKET_DATA_UNAVAILABLE" would have authorised a
    terminal REJECTED. The event type is now part of the proof.
    """
    from crypto_trader.domain.enums import OrderEventType

    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id="sim_reached")
    # A legitimate cancel-pending event that carries the proven reason text.
    await mgr.transition(
        order.internal_order_id,
        OrderEventType.ORDER_CANCEL_PENDING,
        payload={"reason": "MARKET_DATA_UNAVAILABLE"},
    )

    from crypto_trader.runtime.recovery import RecoveryService as _RS

    service = _RS(mgr, _Adapter(OrderNotFound("x")))
    events = await mgr.list_events(order.internal_order_id)
    assert str(events[-1].event_type.value) == "ORDER_CANCEL_PENDING"
    assert (events[-1].payload or {}).get("reason") == "MARKET_DATA_UNAVAILABLE"
    # Same reason, unrelated type -> must NOT be pre-broker proof.
    assert (
        await service._pre_broker_lineage_proven(
            await mgr.get(order.internal_order_id)
        )
        is False
    )


@pytest.mark.asyncio
async def test_lineage_rejects_unproven_reason_on_unknown_event(database):
    """ORDER_UNKNOWN with a non-proven reason is ambiguity, not proof."""
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id=None)
    await mgr.mark_unknown(order.internal_order_id, "TIMEOUT")

    from crypto_trader.runtime.recovery import RecoveryService as _RS

    service = _RS(mgr, _Adapter(OrderNotFound("x")))
    assert await service._pre_broker_lineage_proven(await mgr.get(order.internal_order_id)) is False


@pytest.mark.asyncio
async def test_lineage_rejects_when_broker_id_exists(database):
    """A broker id proves the venue was reached, so lineage cannot be pre-broker."""
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id="sim_reached")
    await mgr.mark_unknown(order.internal_order_id, "MARKET_DATA_UNAVAILABLE")

    from crypto_trader.runtime.recovery import RecoveryService as _RS

    service = _RS(mgr, _Adapter(OrderNotFound("x")))
    assert await service._pre_broker_lineage_proven(await mgr.get(order.internal_order_id)) is False


@pytest.mark.asyncio
async def test_lineage_accepts_explicit_broker_reached_false(database):
    """Explicit broker_reached=False is positive proof regardless of reason text."""
    from crypto_trader.domain.enums import OrderEventType

    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id=None)
    await mgr.transition(
        order.internal_order_id,
        OrderEventType.ORDER_UNKNOWN,
        payload={"reason": "SOMETHING_ELSE", "broker_reached": False},
    )

    from crypto_trader.runtime.recovery import RecoveryService as _RS

    service = _RS(mgr, _Adapter(OrderNotFound("x")))
    assert await service._pre_broker_lineage_proven(
        await mgr.get(order.internal_order_id)
    ) is True


@pytest.mark.asyncio
async def test_lineage_blocks_terminalisation_when_fill_exists(database):
    """Even with proven pre-broker lineage, a durable fill must prevent REJECTED."""
    mgr = OrderManager(database.session_factory)
    order = await _make_order(mgr, ack_id=None)
    await mgr.mark_unknown(order.internal_order_id, "MARKET_DATA_UNAVAILABLE")
    async with database.session_factory() as session:
        session.add(
            FillORM(
                fill_id="fill_p02_lineage",
                order_id=order.internal_order_id,
                symbol=SYMBOL,
                side=OrderSide.BUY.value,
                price=Decimal("100"),
                quantity=Decimal("1"),
                fee=Decimal("0"),
                timestamp=order.created_at,
            )
        )
        await session.commit()

    adapter = _Adapter(OrderNotFound("x"))
    service = RecoveryService(mgr, adapter)
    await service.recover("run_lineage_fill")

    restored = await mgr.get(order.internal_order_id)
    assert restored.status != OrderStatus.REJECTED, (
        "a durable fill outranks even proven pre-broker lineage"
    )
    assert adapter.submit_calls == 0
