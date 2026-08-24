from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from crypto_trader.domain.models import Fill, Instrument, Order, OrderIntent
from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType


def test_instrument_defaults():
    inst = Instrument(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")
    assert inst.tick_size == Decimal("0.00000001")


def test_order_intent_requires_decimal_qty():
    with pytest.raises(ValidationError):
        OrderIntent(client_order_id="c1", symbol="BTCUSDT", side=OrderSide.BUY, quantity=1.5)
    intent = OrderIntent(
        client_order_id="c1", symbol="BTCUSDT", side=OrderSide.BUY, quantity="1.5", price="10"
    )
    assert intent.quantity == Decimal("1.5")


def test_order_remaining_quantity():
    now = datetime.now(timezone.utc)
    order = Order(
        internal_order_id="ord_1", client_order_id="c1", symbol="BTCUSDT",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, time_in_force='GTC', quantity="2",
        filled_quantity="0.5", created_at=now, updated_at=now,
    )
    assert order.remaining_quantity == Decimal("1.5")
    assert order.status == OrderStatus.CREATED


def test_fill_model_decimal():
    fill = Fill(fill_id="f1", order_id="o1", symbol="BTCUSDT", side=OrderSide.BUY,
                price="100.5", quantity="0.25", timestamp=datetime.now(timezone.utc))
    assert fill.price == Decimal("100.5")
