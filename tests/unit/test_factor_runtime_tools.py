from datetime import UTC, datetime

from crypto_trader.llm.tools.factor_runtime import register_factor_runtime_tools
from crypto_trader.llm.tools.registry import LLMToolRegistry


class Factors:
    async def latest_snapshot(self, symbol):
        return {"symbol": symbol, "timestamp": "2026-01-01T00:00:00+00:00", "value": 1}

    async def recent_values(self, symbol, limit):
        return [{"symbol": symbol, "timestamp": "2026-01-01T00:01:00+00:00"}]

    async def recent_performance(self, symbol, limit):
        return [{"symbol": symbol, "timestamp": "2026-01-01T00:02:00+00:00"}]


async def test_factor_service_tools_are_selectively_callable_and_symbol_bound():
    registry = LLMToolRegistry()
    register_factor_runtime_tools(registry, Factors())
    assert {
        "factor_snapshot",
        "factor_history",
        "factor_performance",
        "factor_health",
    } <= set(registry.available())
    assert registry.catalog()["factor_history"] == "Last 100 factor observations"
    result = await registry.call(
        "factor_snapshot", "ETHUSDT", {"as_of": datetime(2026, 1, 2, tzinfo=UTC)}
    )
    assert result.symbol == "ETHUSDT"
    assert result.features["rows"][0]["symbol"] == "ETHUSDT"
    assert result.timestamp == datetime(2026, 1, 1, tzinfo=UTC)


async def test_factor_health_tool_reuses_canonical_evaluator_thresholds():
    class HealthFactors(Factors):
        async def recent_performance(self, symbol, limit):
            return [
                {
                    "factor_name": "momentum",
                    "symbol": symbol,
                    "timeframe": "15m",
                    "sample_size": 30,
                    "win_rate": "0.40",
                    "sharpe": "0.8",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                },
                {
                    "factor_name": "trend",
                    "symbol": symbol,
                    "timeframe": "15m",
                    "sample_size": 30,
                    "win_rate": "0.60",
                    "sharpe": "0.9",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                },
            ]

    registry = LLMToolRegistry()
    register_factor_runtime_tools(registry, HealthFactors())
    result = await registry.call(
        "factor_health", "BTCUSDT", {"as_of": datetime(2026, 1, 2, tzinfo=UTC)}
    )
    rows = {row["factor_name"]: row for row in result.features["rows"]}
    assert rows["momentum"]["status"] == "DEGRADING"
    assert rows["trend"]["status"] == "HEALTHY"
