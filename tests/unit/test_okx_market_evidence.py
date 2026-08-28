from __future__ import annotations

from decimal import Decimal

import pytest

from crypto_trader.market_data.okx_public_data import OKXPublicDataClient
from crypto_trader.market_data.public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.technical_indicators import calculate_technical_indicators


class FakeOKX:
    async def _public_request(self, method, path, params=None):
        if path == "/api/v5/market/ticker":
            return {
                "code": "0",
                "data": [{
                    "instId": "BTC-USDT-SWAP",
                    "last": "120",
                    "lastSz": "2",
                    "askPx": "120.1",
                    "askSz": "7",
                    "bidPx": "119.9",
                    "bidSz": "8",
                    "open24h": "100",
                    "high24h": "125",
                    "low24h": "95",
                    "volCcy24h": "1234.5",
                    "vol24h": "9999",
                    "sodUtc0": "101",
                    "sodUtc8": "102",
                    "ts": "1700000000000",
                }],
            }
        if path == "/api/v5/market/history-candles":
            after = str((params or {}).get("after") or "")
            if after == "1000":
                return {"code": "0", "data": []}
            return {
                "code": "0",
                "data": [
                    ["2000", "10", "12", "9", "11", "5", "50", "55", "1"],
                    ["1000", "9", "11", "8", "10", "4", "40", "44", "1"],
                ],
            }
        raise AssertionError(path)

    async def get_orderbook(self, inst_id, limit=100):
        return {
            "data": [{
                "ts": "1700000000000",
                "bids": [["119.9", "3", "0", "1"]],
                "asks": [["120.1", "2", "0", "1"]],
            }]
        }

    async def get_public_mark_price(self, inst_id):
        return {"markPx": "120.02"}

    async def get_public_index_ticker(self, inst_id):
        return {"idxPx": "119.98"}

    async def get_public_funding_rate(self, inst_id):
        return {"fundingRate": "0.0001", "fundingTime": "1700003600000"}

    async def get_public_open_interest(self, inst_id):
        return {"oi": "10000", "oiCcy": "100", "oiUsd": "1200000"}

    async def disconnect(self):
        return None


@pytest.mark.asyncio
async def test_okx_feed_preserves_full_ticker_and_computes_24h_change():
    feed = OKXPublicMarketFeed(client=FakeOKX())
    state = await feed.refresh()

    assert state.price == Decimal("120")
    assert state.open_24h == Decimal("100")
    assert state.high_24h == Decimal("125")
    assert state.low_24h == Decimal("95")
    assert state.price_change_24h == Decimal("20")
    assert state.price_change_percent_24h == Decimal("0.2")
    assert state.best_bid_size == Decimal("8")
    assert state.best_ask_size == Decimal("7")
    assert state.last_size == Decimal("2")
    assert state.open_interest_ccy == Decimal("100")
    assert state.open_interest_usd == Decimal("1200000")


@pytest.mark.asyncio
async def test_okx_history_backfill_deduplicates_and_orders_oldest_first():
    client = OKXPublicDataClient(FakeOKX())
    rows = await client.backfill_candles("BTC-USDT-SWAP", max_pages=3)
    assert [row[0] for row in rows] == ["1000", "2000"]


def _candles(count: int) -> list[dict]:
    rows = []
    for i in range(count):
        close = 100 + i * 0.25 + ((i % 7) - 3) * 0.05
        rows.append({
            "open": str(close - 0.1),
            "high": str(close + 0.5),
            "low": str(close - 0.5),
            "close": str(close),
            "volume": str(1000 + i * 3),
        })
    return rows


def test_technical_indicator_bundle_is_advisory_and_broad():
    evidence = calculate_technical_indicators(_candles(220))
    indicators = evidence["indicators"]

    assert evidence["authority"] == "ADVISORY"
    assert evidence["status"] == "OK"
    assert evidence["available_indicator_count"] >= 35
    for key in (
        "ema_200",
        "rsi_14",
        "macd_12_26",
        "bollinger_upper_20_2",
        "atr_14",
        "adx_14",
        "stochastic_k_14",
        "mfi_14",
        "vwap_20",
        "donchian_high_50",
        "keltner_upper_20",
        "senkou_b_52",
    ):
        assert indicators[key] is not None


def test_technical_indicator_bundle_never_fabricates_missing_history():
    evidence = calculate_technical_indicators(_candles(10))
    assert evidence["authority"] == "ADVISORY"
    assert evidence["indicators"]["ema_200"] is None
    assert evidence["indicators"]["adx_14"] is None
