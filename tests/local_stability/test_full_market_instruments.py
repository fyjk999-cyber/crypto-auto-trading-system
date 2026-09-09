"""Full-market instrument specs for the paper adapter (live-llm entry path).

The engine calls adapter.get_exchange_info() with no symbol and stores the
result as its instrument registry. A single-symbol registry made every
full-market DeepSeek entry decision fail sizing with
LIVE_LLM_SIZING_UNAVAILABLE (ctx.instrument is None). These tests pin the
factual full-market behavior: every returned instrument is parsed from the
public OKX instruments response, filtered to live USDT linear swaps.
"""

from decimal import Decimal

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
