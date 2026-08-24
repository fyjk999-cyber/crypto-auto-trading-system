from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce, TradingMode
from crypto_trader.domain.errors import IdempotencyConflict
from crypto_trader.domain.models import Fill, OrderIntent
from crypto_trader.order.manager import OrderManager


def make_intent(cid="client_1", symbol="BTCUSDT", qty="1"):
    return OrderIntent(
        client_order_id=cid, symbol=symbol, side=OrderSide.BUY,
        order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
        price="100", quantity=qty, strategy_id="test",
    )


def make_fill(order, fill_id="fill_1", qty="0.4", price="100", ts=None, exchange_order_id=None):
    return Fill(
        fill_id=fill_id, trade_id=None, order_id=order.internal_order_id,
        client_order_id=order.client_order_id, exchange_order_id=exchange_order_id or order.exchange_order_id,
        symbol=order.symbol, side=order.side, price=price, quantity=qty,
        fee="0.01", fee_currency="USDT", timestamp=ts or datetime.now(timezone.utc),
    )


async def test_idempotent_create_same_client_order_id(database):
    mgr = OrderManager(database.session_factory)
    intent = make_intent()
    o1 = await mgr.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    o2 = await mgr.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    assert o1.internal_order_id == o2.internal_order_id
    rows = await mgr.list_open()
    assert [o.internal_order_id for o in rows].count(o1.internal_order_id) == 0
    all_events = await mgr.list_events(o1.internal_order_id)
    assert sum(1 for e in all_events if e.event_type.value == "ORDER_CREATED") == 1


async def test_idempotency_conflict_different_payload(database):
    mgr = OrderManager(database.session_factory)
    await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    with pytest.raises(IdempotencyConflict):
        await mgr.create_from_intent(make_intent(qty="2"), trading_mode=TradingMode.PAPER)


async def test_full_async_lifecycle(database):
    mgr = OrderManager(database.session_factory)
    order = await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    order = await mgr.validate(order.internal_order_id)
    order = await mgr.submitting(order.internal_order_id)
    order = await mgr.submitted(order.internal_order_id)
    order = await mgr.ack(order.internal_order_id, "ex_1")
    assert order.status == OrderStatus.ACKNOWLEDGED
    assert order.exchange_order_id == "ex_1"
    order = await mgr.opened(order.internal_order_id)
    assert order.status == OrderStatus.OPEN


async def test_fill_before_ack(database):
    mgr = OrderManager(database.session_factory)
    order = await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    order, fill, applied = await mgr.apply_fill(make_fill(order, exchange_order_id="ex_early", qty="0.5"))
    assert applied is True
    assert order.status == OrderStatus.PARTIALLY_FILLED
    # ack arrives late: recorded, no regression
    order = await mgr.ack(order.internal_order_id, "ex_early", event_id="evt_ack_late")
    assert order.status == OrderStatus.PARTIALLY_FILLED


async def test_partial_then_full_fill(database):
    mgr = OrderManager(database.session_factory)
    order = await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.ack(order.internal_order_id, "ex_2")
    await mgr.opened(order.internal_order_id)
    order, _, _ = await mgr.apply_fill(make_fill(order, qty="0.25", price="100"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    order, _, _ = await mgr.apply_fill(make_fill(order, fill_id="fill_2", qty="0.75", price="101"))
    assert order.status == OrderStatus.FILLED
    assert order.avg_fill_price == Decimal("100.75")


async def test_duplicate_fill_is_single_application(database):
    applied = []
    async def settle(fill):
        applied.append(fill.fill_id)
    mgr = OrderManager(database.session_factory, settlement_callback=settle)
    order = await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.ack(order.internal_order_id, "ex_3")
    await mgr.opened(order.internal_order_id)
    fill = make_fill(order, qty="0.5")
    _, _, first = await mgr.apply_fill(fill)
    _, _, second = await mgr.apply_fill(fill)
    assert first is True and second is False
    assert applied == ["fill_1"]
    order = await mgr.get(order.internal_order_id)
    assert order.filled_quantity == Decimal("0.5")


async def test_cancel_fill_race(database):
    mgr = OrderManager(database.session_factory)
    order = await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.ack(order.internal_order_id, "ex_4")
    await mgr.opened(order.internal_order_id)
    await mgr.cancel_pending(order.internal_order_id)
    order, _, _ = await mgr.apply_fill(make_fill(order, qty="1"))
    assert order.status == OrderStatus.FILLED


async def test_unknown_recovery(database):
    mgr = OrderManager(database.session_factory)
    order = await mgr.create_from_intent(make_intent(), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.mark_unknown(order.internal_order_id, "rest timeout")
    assert (await mgr.get(order.internal_order_id)).status == OrderStatus.UNKNOWN
    order = await mgr.transition(order.internal_order_id, __import__("crypto_trader.domain.enums", fromlist=["OrderEventType"]).OrderEventType.ORDER_OPENED)
    assert order.status == OrderStatus.OPEN
