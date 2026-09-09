from __future__ import annotations

from tests.conftest import make_paper_engine


class BrokenStrategy:
    name = "broken_strategy"

    async def on_market_data(self, _ctx):
        raise ValueError("sensitive provider response must not be exposed")


async def test_strategy_health_reports_safe_exception_class_without_message(database):
    engine = make_paper_engine(
        database,
        strategy=BrokenStrategy(),
        engine_tick_seconds=3600,
    )
    await engine.start("run-health-diagnostic")

    await engine.tick()

    component = engine.health.snapshot()["components"]["strategy:broken_strategy"]
    assert component["ok"] is False
    assert component["detail"] == "ValueError"
    assert "sensitive" not in str(component)
    await engine.stop()



async def test_execution_market_refresh_succeeds_on_healthy_engine(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-market-refresh-ok")
    assert await engine._refresh_execution_market("BTCUSDT") is True
    assert engine.health.snapshot()["components"]["market_data"]["ok"] is True
    await engine.stop()


async def test_execution_market_refresh_failure_marks_health_false():
    from crypto_trader.market_data.service import MarketDataService
    from crypto_trader.runtime.engine import TradingEngine
    from crypto_trader.runtime.health import HealthRegistry

    class BrokenAdapter:
        async def get_orderbook(self, symbol):
            raise RuntimeError("down")

    engine = object.__new__(TradingEngine)
    engine.market_data = MarketDataService()
    engine.health = HealthRegistry()
    engine.adapter = BrokenAdapter()
    assert await engine._refresh_execution_market("BTCUSDT") is False
    assert engine.health.snapshot()["components"]["market_data"]["ok"] is False
