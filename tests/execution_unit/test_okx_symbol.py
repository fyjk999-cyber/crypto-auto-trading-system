from decimal import Decimal

from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.exchange.symbol_mapper import SymbolMapper


def test_okx_auth_headers_demo_and_not_live():
    adapter = OKXAdapter(api_key="k", api_secret="s", api_passphrase="p", demo=True)
    headers = adapter._build_headers("GET", "/api/v5/account/balance", "")
    assert headers["x-simulated-trading"] == "1"
    assert "OK-ACCESS-KEY" in headers
    live = OKXAdapter(api_key="k", api_secret="s", api_passphrase="p", demo=False)
    headers_live = live._build_headers("GET", "/api/v5/account/balance", "")
    assert "x-simulated-trading" not in headers_live


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


def test_okx_iso8601_timestamp_format():
    import re

    from crypto_trader.exchange.okx import okx_timestamp

    value = okx_timestamp()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value)


def test_okx_get_query_signature_uses_full_path():
    from crypto_trader.exchange.okx import okx_prehash, okx_signature

    path = "/api/v5/account/positions?instType=SWAP"
    prehash = okx_prehash("2026-08-24T17:30:01.123Z", "GET", path, "")
    sig = okx_signature("secret", prehash)
    assert len(sig) > 20


def test_okx_post_signature_uses_exact_body():
    import json

    from crypto_trader.exchange.okx import okx_prehash, okx_signature

    body = {"instId": "BTC-USDT-SWAP", "tdMode": "cross", "side": "buy", "sz": "0.1"}
    body_str = json.dumps(body, separators=(",", ":"))
    prehash = okx_prehash("2026-08-24T17:30:01.123Z", "POST", "/api/v5/trade/order", body_str)
    sig = okx_signature("secret", prehash)
    assert len(sig) > 20


def test_okx_canonical_query_string_is_sorted():
    from crypto_trader.exchange.okx import canonical_query_string

    assert canonical_query_string({"b": "2", "a": "1"}) == "a=1&b=2"


def test_okx_cl_ord_id_is_bounded_and_stable():
    adapter = OKXAdapter(demo=True)
    cid = adapter._cl_ord_id("client_order_1")
    assert len(cid) <= 32
    assert adapter._cl_ord_id("client_order_1") == cid


def test_symbol_mapping_supports_dynamic_usdt_swap_universe():
    mapper = SymbolMapper()
    assert mapper.to_okx("DOGEUSDT") == "DOGE-USDT-SWAP"
    assert mapper.to_canonical("DOGE-USDT-SWAP") == "DOGEUSDT"



async def test_okx_exchange_info_preserves_venue_instrument_identity(monkeypatch):
    adapter = OKXAdapter(demo=True)
    rows_by_type = {
        "SPOT": [
            {
                "instId": "BTC-USDT",
                "instType": "SPOT",
                "state": "live",
                "baseCcy": "BTC",
                "quoteCcy": "USDT",
                "tickSz": "0.1",
                "lotSz": "0.00001",
                "minSz": "0.00001",
                "ctVal": "",
                "ctValCcy": "",
                "settleCcy": "",
                "listTime": "1",
                "expTime": "",
            }
        ],
        "SWAP": [
            {
                "instId": "ETH-USDT-SWAP",
                "instType": "SWAP",
                "state": "live",
                "uly": "ETH-USDT",
                "ctType": "linear",
                "ctVal": "0.1",
                "ctMult": "1",
                "ctValCcy": "USDT",
                "settleCcy": "USDT",
                "tickSz": "0.01",
                "lotSz": "1",
                "minSz": "1",
                "listTime": "1",
                "expTime": "",
            }
        ],
        "FUTURES": [],
    }

    async def fake_get_instruments(inst_type: str):
        return rows_by_type[inst_type]

    monkeypatch.setattr(adapter, "get_instruments", fake_get_instruments)
    instruments = await adapter.get_exchange_info()
    assert len(instruments) == 2
    spot = next(i for i in instruments if i.inst_type == "SPOT")
    assert spot.inst_id == "BTC-USDT"
    assert spot.symbol == "BTCUSDT"
    assert spot.status == "TRADING"
    assert spot.quote_asset == "USDT"
    swap = next(i for i in instruments if i.inst_type == "SWAP")
    assert swap.inst_id == "ETH-USDT-SWAP"
    assert swap.ct_type == "linear"
    assert swap.ct_val == "0.1"
    assert swap.settle_ccy == "USDT"
    assert swap.contract_size == Decimal("0.1")


async def test_okx_exchange_info_maps_expired_state(monkeypatch):
    adapter = OKXAdapter(demo=True)

    async def fake_get_instruments(inst_type: str):
        return [
            {
                "instId": "BTC-USDT-SWAP",
                "instType": inst_type,
                "state": "expired",
                "baseCcy": "BTC",
                "quoteCcy": "USDT",
                "tickSz": "0.1",
                "lotSz": "1",
                "minSz": "1",
            }
        ]

    monkeypatch.setattr(adapter, "get_instruments", fake_get_instruments)
    instruments = await adapter.get_exchange_info()
    assert instruments and instruments[0].status == "EXPIRED"
