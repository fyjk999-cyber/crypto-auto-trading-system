from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce, TradingMode
from crypto_trader.domain.errors import AuthenticationError, ExchangeUnavailable, RateLimited
from crypto_trader.domain.models import Order
from crypto_trader.exchange.binance import BinanceAdapter
from crypto_trader.exchange.bybit import BybitAdapter
from crypto_trader.exchange.okx import OKXAdapter


def make_adapter(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://test.binance", transport=transport)
    return BinanceAdapter(base_url="https://test.binance", ws_base_url="wss://test.binance",
                          api_key="key", api_secret="secret", client=client)


async def test_get_orderbook_normalizes_float_json_to_decimal():
    def handler(request):
        return httpx.Response(200, json={
            "lastUpdateId": 123,
            "bids": [["100.5", "1.25"], ["100.1", "2.0"]],
            "asks": [["100.6", "0.5"], ["100.9", "3.0"]],
        })
    adapter = make_adapter(handler)
    await adapter.connect()
    book = await adapter.get_orderbook("BTCUSDT")
    assert book.sequence == 123
    assert book.best_bid().price == Decimal("100.5")
    assert book.best_ask().price == Decimal("100.6")
    assert book.best_ask().quantity == Decimal("0.5")


async def test_get_exchange_info_filters():
    def handler(request):
        return httpx.Response(200, json={"symbols": [{
            "symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01000000", "pricePrecision": 2},
                {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000", "quantityPrecision": 5},
                {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
            ],
        }]})
    adapter = make_adapter(handler)
    await adapter.connect()
    info = await adapter.get_exchange_info()
    assert info[0].tick_size == Decimal("0.01")
    assert info[0].step_size == Decimal("0.00001")
    assert info[0].min_notional == Decimal("5")


async def test_rate_limit_error_is_normalized():
    def handler(request):
        return httpx.Response(429, json={"code": -1003, "msg": "Too much request weight used"})
    adapter = make_adapter(handler)
    await adapter.connect()
    with pytest.raises(RateLimited):
        await adapter.get_orderbook("BTCUSDT")


async def test_auth_error_is_normalized():
    def handler(request):
        return httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key"})
    adapter = make_adapter(handler)
    await adapter.connect()
    with pytest.raises(AuthenticationError):
        await adapter.get_balances()


async def test_5xx_error_is_normalized():
    def handler(request):
        return httpx.Response(500, text="internal error")
    adapter = make_adapter(handler)
    await adapter.connect()
    with pytest.raises(ExchangeUnavailable):
        await adapter.get_orderbook("BTCUSDT")


async def test_submit_order_signs_and_normalizes():
    seen = {}
    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={
            "symbol": "BTCUSDT", "orderId": 42, "clientOrderId": "c1",
            "side": "BUY", "type": "LIMIT", "timeInForce": "GTC",
            "price": "100.00000000", "origQty": "0.01000000",
            "executedQty": "0", "status": "NEW",
        })
    adapter = make_adapter(handler)
    await adapter.connect()
    order = Order(internal_order_id="ord_1", client_order_id="c1", symbol="BTCUSDT",
                  side=OrderSide.BUY, order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
                  price="100", quantity="0.01", status=OrderStatus.SUBMITTING,
                  trading_mode=TradingMode.PAPER, created_at=datetime.now(timezone.utc),
                  updated_at=datetime.now(timezone.utc))
    normalized = await adapter.submit_order(order)
    assert normalized.exchange_order_id == "42"
    assert normalized.status == OrderStatus.ACKNOWLEDGED
    assert "signature" in seen["params"]
    assert seen["params"]["newClientOrderId"] == "c1"


async def test_normalize_fill_converts_floats_exactly_as_strings():
    adapter = BinanceAdapter()
    fill = adapter.normalize_fill({
        "e": "executionReport", "s": "BTCUSDT", "i": 7, "c": "c1",
        "p": "100.12500000", "q": "0.00100000", "n": "0.00001000",
        "T": 1700000000123,
    })
    assert fill.price == Decimal("100.125")
    assert fill.quantity == Decimal("0.001")
    assert fill.fee == Decimal("0.00001")


async def test_okx_and_bybit_boundaries_exist():
    okx = OKXAdapter()
    bybit = BybitAdapter()
    await okx.connect()
    await bybit.connect()
    with pytest.raises(NotImplementedError):
        await okx.get_balances()
    with pytest.raises(NotImplementedError):
        await bybit.get_orderbook("BTCUSDT")
