from datetime import UTC, datetime, timedelta

from crypto_trader.llm.tools.market_history import register_market_history_tool
from crypto_trader.llm.tools.registry import LLMToolRegistry


class Client:
    def __init__(self, as_of):
        self.as_of = as_of

    async def get_candles(self, instrument_id, interval, limit):
        assert instrument_id == "ETH-USDT-SWAP" and limit == 60
        past = int((self.as_of - timedelta(minutes=1)).timestamp() * 1000)
        future = int((self.as_of + timedelta(minutes=1)).timestamp() * 1000)
        return [
            [str(future), "1", "2", "1", "2", "9", "0", "0", "1"],
            [str(past), "1", "2", "1", "2", "7", "0", "0", "1"],
        ]


class Feed:
    def __init__(self, as_of):
        self.client = Client(as_of)

    def provider_symbol(self, symbol):
        assert symbol == "ETHUSDT"
        return "ETH-USDT-SWAP"


async def test_multi_timeframe_history_is_closed_bounded_and_as_of_safe():
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    registry = LLMToolRegistry()
    register_market_history_tool(registry, Feed(as_of))
    result = await registry.call(
        "multi_timeframe_history", "ETHUSDT", {"as_of": as_of}
    )
    assert result.data_quality == "FACTUAL_OKX_CLOSED"
    assert set(result.features) == {"1m", "15m", "1H"}
    assert all(len(rows) == 1 for rows in result.features.values())
    assert all(rows[0]["volume"] == "7" for rows in result.features.values())
    assert result.timestamp < as_of
