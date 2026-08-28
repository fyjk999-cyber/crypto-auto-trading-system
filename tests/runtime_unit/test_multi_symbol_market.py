from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.config import Settings
from crypto_trader.exchange.symbol_mapper import DEFAULT_TRADING_SYMBOLS, SymbolMapper
from crypto_trader.runtime.live_decision_context import LiveDecisionContextProvider
from crypto_trader.runtime.multi_symbol_chief_trader import MultiSymbolChiefTraderStrategyAdapter
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter


def test_default_symbol_universe_contains_20_unique_supported_coins():
    settings = Settings(_env_file=None)
    assert settings.symbol_universe == DEFAULT_TRADING_SYMBOLS
    assert len(settings.symbol_universe) == 20
    assert len(set(settings.symbol_universe)) == 20
    mapper = SymbolMapper()
    for symbol in settings.symbol_universe:
        assert mapper.to_canonical(mapper.to_okx(symbol)) == symbol


def test_symbol_mapper_uses_okx_usdt_swap_contracts():
    mapper = SymbolMapper()
    assert mapper.to_okx("BTCUSDT") == "BTC-USDT-SWAP"
    assert mapper.to_okx("ETHUSDT") == "ETH-USDT-SWAP"
    assert mapper.to_okx("BNBUSDT") == "BNB-USDT-SWAP"
    assert mapper.to_okx("UNIUSDT") == "UNI-USDT-SWAP"
    with pytest.raises(ValueError):
        mapper.to_okx("UNKNOWNUSDT")


def test_multi_symbol_chief_trader_rotates_one_symbol_per_context_request():
    adapter = MultiSymbolChiefTraderStrategyAdapter(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT")
    )
    assert [adapter.symbol for _ in range(5)] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BTCUSDT",
        "ETHUSDT",
    ]


class _StubFeed:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.client = object()

    async def close(self) -> None:
        return None


def test_paper_real_market_adapter_keeps_feed_state_isolated_per_symbol():
    adapter = PaperRealMarketAdapter(feed_factory=_StubFeed)
    btc = adapter._feed_for("BTCUSDT")
    eth = adapter._feed_for("ETHUSDT")
    sol = adapter._feed_for("SOLUSDT")
    assert btc.symbol == "BTCUSDT"
    assert eth.symbol == "ETHUSDT"
    assert sol.symbol == "SOLUSDT"
    assert btc is not eth
    assert eth is not sol
    assert adapter._feed_for("ETHUSDT") is eth


@pytest.mark.asyncio
async def test_live_decision_context_builds_independent_symbol_evidence():
    start = datetime(2026, 1, 1, tzinfo=UTC)

    async def candles(symbol: str) -> list[dict]:
        bias = 100 if symbol == "BTCUSDT" else 200
        return [
            {
                "symbol": symbol,
                "interval": "1m",
                "open_time": (start + timedelta(minutes=index)).isoformat(),
                "open": str(bias + index * 0.1),
                "high": str(bias + index * 0.1 + 0.2),
                "low": str(bias + index * 0.1 - 0.2),
                "close": str(bias + index * 0.1 + 0.1),
                "volume": "100",
                "source": "TEST_REAL_SHAPE",
            }
            for index in range(80)
        ]

    provider = LiveDecisionContextProvider(candle_provider=candles, symbol="BTCUSDT")
    btc = await provider.build({}, symbol="BTCUSDT")
    eth = await provider.build({}, symbol="ETHUSDT")
    assert btc is not None
    assert eth is not None
    assert btc.evidence["symbol"] == "BTCUSDT"
    assert eth.evidence["symbol"] == "ETHUSDT"
    assert set(provider._evidence_builders) == {"BTCUSDT", "ETHUSDT"}
