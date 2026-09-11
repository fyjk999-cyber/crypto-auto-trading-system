from datetime import UTC, datetime, timedelta

from crypto_trader.llm.tools.market_history import register_market_history_tool
from crypto_trader.llm.tools.registry import LLMToolRegistry

DURATION = {"1m": timedelta(minutes=1), "15m": timedelta(minutes=15), "1H": timedelta(hours=1)}


class Client:
    def __init__(self, as_of, *, extra_rows=None):
        self.as_of = as_of
        self.extra_rows = list(extra_rows or [])
        self.requests = []

    async def get_candles(self, instrument_id, interval, limit):
        assert instrument_id == "ETH-USDT-SWAP" and limit == 60
        self.requests.append(interval)
        duration = DURATION[interval]
        closed_open = int((self.as_of - duration).timestamp() * 1000)
        future_open = int(self.as_of.timestamp() * 1000)
        return [
            [str(future_open), "1", "2", "1", "2", "9", "0", "0", "1"],
            [str(closed_open), "1", "2", "1", "2", "7", "0", "0", "1"],
            *self.extra_rows,
        ]


class Feed:
    def __init__(self, as_of, *, extra_rows=None):
        self.client = Client(as_of, extra_rows=extra_rows)

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


async def test_hour_candle_open_before_as_of_but_unfinished_is_rejected():
    as_of = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    hour_open = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    quarter_open = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    extra = [
        [str(int(hour_open.timestamp() * 1000)), "1", "2", "1", "2", "8", "0", "0", "1"],
        [str(int(quarter_open.timestamp() * 1000)), "1", "2", "1", "2", "8", "0", "0", "1"],
        [
            str(int((as_of - timedelta(minutes=1)).timestamp() * 1000)),
            "1", "2", "1", "2", "9", "0", "0", "0",
        ],
    ]
    registry = LLMToolRegistry()
    register_market_history_tool(registry, Feed(as_of, extra_rows=extra))
    result = await registry.call(
        "multi_timeframe_history", "ETHUSDT", {"as_of": as_of}
    )
    rows_1h = result.features["1H"]
    rows_15m = result.features["15m"]
    # 12:00-13:00 1H candle is not closed at 12:30 even with confirm=1.
    assert all(row["timestamp"] != hour_open.isoformat() for row in rows_1h)
    # 12:00-12:15 15m candle is fully closed at 12:30.
    assert quarter_open.isoformat() in {row["timestamp"] for row in rows_15m}
    # confirm=0 is never evidence, even when the interval is closed.
    assert all(row["volume"] != "9" for rows in result.features.values() for row in rows)
