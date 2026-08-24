from crypto_trader.exchange.okx import OKXAdapter


def test_okx_auth_headers_demo_and_not_live():
    adapter = OKXAdapter(api_key="k", api_secret="s", api_passphrase="p", demo=True)
    headers = adapter._headers("GET", "/api/v5/account/balance", "")
    assert headers["x-simulated-trading"] == "1"
    assert "OK-ACCESS-KEY" in headers


def test_okx_normalize_order():
    adapter = OKXAdapter(demo=True)
    order = adapter.normalize_order(
        {
            "instId": "BTC-USDT-SWAP",
            "ordId": "123",
            "clOrdId": "c1",
            "side": "buy",
            "ordType": "limit",
            "px": "100",
            "sz": "0.1",
            "accFillSz": "0",
            "state": "live",
        }
    )
    assert order.symbol == "BTCUSDT"
    assert order.exchange_order_id == "123"
    assert order.price == 100


def test_okx_normalize_fill():
    adapter = OKXAdapter(demo=True)
    fill = adapter.normalize_fill(
        {
            "instId": "BTC-USDT-SWAP",
            "ordId": "123",
            "clOrdId": "c1",
            "side": "sell",
            "fillPx": "99.5",
            "fillSz": "0.1",
            "fee": "0.01",
            "feeCcy": "USDT",
            "ts": 1700000000000,
        }
    )
    assert fill.symbol == "BTCUSDT"
    assert fill.price == 99.5
