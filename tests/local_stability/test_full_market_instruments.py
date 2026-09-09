"""Full-market instrument specs for the paper adapter (live-llm entry path).

The engine calls adapter.get_exchange_info() with no symbol and stores the
result as its instrument registry. A single-symbol registry made every
full-market DeepSeek entry decision fail sizing with
LIVE_LLM_SIZING_UNAVAILABLE (ctx.instrument is None). These tests pin the
factual full-market behavior: every returned instrument is parsed from the
public OKX instruments response, filtered to live USDT linear swaps.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter


def _row(
    inst_id,
    *,
    state="live",
    ct_type="linear",
    tick="0.0001",
    lot="1",
    min_sz="1",
    ct_val="10",
):
    return {
        "instId": inst_id,
        "instType": "SWAP",
        "ctType": ct_type,
        "state": state,
        "tickSz": tick,
        "lotSz": lot,
        "minSz": min_sz,
        "ctVal": ct_val,
        "ctMult": "1",
    }


class FullMarketOKX:
    def __init__(self, rows=None, fail=False):
        self.rows = rows if rows is not None else [
            _row("BTC-USDT-SWAP", tick="0.1", lot="0.01", min_sz="0.01", ct_val="0.01"),
            _row("ETH-USDT-SWAP", tick="0.01", lot="1", min_sz="1", ct_val="0.1"),
            _row("ARB-USDT-SWAP", state="suspend"),
            _row("BTC-USD-SWAP"),
            _row("DOGE-USDT-SWAP", lot="0"),
        ]
        self.fail = fail
        self.calls = 0

    async def get_instruments(self, instrument_type):
        self.calls += 1
        if self.fail:
            raise RuntimeError("okx unavailable")
        return self.rows

    async def get_ticker(self, _symbol):
        return {
            "last": "100",
            "askPx": "100.1",
            "bidPx": "99.9",
            "open24h": "100",
            "high24h": "101",
            "low24h": "99",
            "volCcy24h": "1000",
            "vol24h": "10",
            "ts": "1700000000000",
        }

    async def get_orderbook(self, _symbol):
        return {
            "data": [
                {
                    "ts": "1700000000000",
                    "bids": [["25.99", "5"]],
                    "asks": [["26.01", "5"]],
                }
            ]
        }

    async def get_mark_price(self, _symbol):
        return {"mark_price": "26.00"}

    async def get_index_price(self, _symbol):
        return {"index_price": "26.00"}

    async def get_funding_rate(self, _symbol):
        return {"funding_rate": "0.0001", "next_funding_time": None}

    async def get_open_interest(self, _symbol):
        return {"open_interest": "12345"}

    async def disconnect(self):
        return None


def _adapter(client):
    return PaperRealMarketAdapter(feed=OKXPublicMarketFeed(client=client))


async def test_get_exchange_info_without_symbol_returns_full_factual_usdt_linear_universe():
    client = FullMarketOKX()
    instruments = await _adapter(client).get_exchange_info()
    symbols = {i.symbol for i in instruments}
    assert symbols == {"BTCUSDT", "ETHUSDT"}
    by_symbol = {i.symbol: i for i in instruments}
    btc = by_symbol["BTCUSDT"]
    assert btc.status == "TRADING"
    assert btc.instrument_type == "LINEAR_PERP"
    assert btc.exchange == "OKX"
    assert btc.base_asset == "BTC"
    assert btc.quote_asset == "USDT"
    assert btc.tick_size == Decimal("0.1")
    assert btc.step_size == Decimal("0.01")
    assert btc.min_qty == Decimal("0.01")
    assert btc.contract_size == Decimal("0.01")
    assert btc.contract_multiplier == Decimal("1")


async def test_get_exchange_info_with_symbol_stays_bounded():
    client = FullMarketOKX()
    instruments = await _adapter(client).get_exchange_info("ETHUSDT")
    assert [i.symbol for i in instruments] == ["ETHUSDT"]


async def test_get_exchange_info_fails_closed_when_okx_unavailable():
    instruments = await _adapter(FullMarketOKX(fail=True)).get_exchange_info()
    assert instruments == []


async def test_engine_registry_would_resolve_reviewed_symbols():
    client = FullMarketOKX()
    adapter = _adapter(client)
    instruments = await adapter.get_exchange_info()
    registry = {i.symbol: i for i in instruments}
    # Symbols DeepSeek actually reviewed and sized on 2026-09-09.
    for symbol in ("BTCUSDT", "ETHUSDT"):
        assert registry[symbol].status == "TRADING"
    # The registry is built only from the factual OKX response.
    assert client.calls == 1


def _make_order(symbol, side, qty, price):
    from uuid import uuid4

    from crypto_trader.domain.enums import (
        OrderStatus,
        OrderType,
        TimeInForce,
        TradingMode,
    )
    from crypto_trader.domain.models import Order

    now = datetime.now(UTC)
    return Order(
        internal_order_id=f"ord_{uuid4().hex[:8]}",
        client_order_id=f"c_{uuid4().hex[:8]}",
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=price,
        quantity=qty,
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        strategy_id="test",
        created_at=now,
        updated_at=now,
    )


async def test_paper_submit_fills_at_real_fetched_price_not_synthetic_seed():
    from crypto_trader.domain.enums import OrderSide, OrderStatus

    # Real VVV-style market: bid/ask ~26. A SELL limit below the real bid must
    # fill at the REAL touch (25.99), never at a synthetic mid=100 seed book.
    client = FullMarketOKX()
    client.get_ticker = _ticker_at("25.99", "26.01")  # type: ignore[method-assign]
    client.get_orderbook = _book_at("25.99", "26.01")  # type: ignore[method-assign]
    adapter = _adapter(client)
    await adapter.connect()
    order = _make_order("VVVUSDT", OrderSide.SELL, "2", "25.50")
    result = await adapter.submit_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_quantity == Decimal("2")
    # Fill price comes from the real fetched bid (25.99), not the 100 seed.
    assert result.avg_fill_price == Decimal("25.99")


def _ticker_at(bid: str, ask: str):
    async def get_ticker(_symbol):
        return {
            "last": bid,
            "askPx": ask,
            "bidPx": bid,
            "open24h": bid,
            "high24h": ask,
            "low24h": bid,
            "volCcy24h": "1000",
            "vol24h": "10",
            "ts": "1700000000000",
        }

    return get_ticker


def _book_at(bid: str, ask: str):
    async def get_orderbook(_symbol):
        return {
            "data": [
                {
                    "ts": "1700000000000",
                    "bids": [[bid, "5"]],
                    "asks": [[ask, "5"]],
                }
            ]
        }

    return get_orderbook


async def test_paper_submit_fails_closed_when_real_feed_unavailable():
    from crypto_trader.domain.enums import OrderSide
    from crypto_trader.domain.errors import OrderRejected

    client = FullMarketOKX()

    async def broken_orderbook(_symbol):
        raise RuntimeError("okx feed down")

    client.get_orderbook = broken_orderbook  # type: ignore[method-assign]
    adapter = _adapter(client)
    await adapter.connect()
    with pytest.raises(OrderRejected):
        await adapter.submit_order(
            _make_order("VVVUSDT", OrderSide.SELL, "1", "26.003")
        )
