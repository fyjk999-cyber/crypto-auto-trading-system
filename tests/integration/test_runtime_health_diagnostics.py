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


async def test_execution_market_refresh_replaces_stale_book(database):
    from datetime import UTC, datetime, timedelta

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-market-refresh-stale")
    assert await engine._strategy_context("BTCUSDT") is not None
    book = engine.market_data.books["BTCUSDT"]
    book.updated_at = datetime.now(UTC) - timedelta(seconds=30)
    assert engine.market_data.is_fresh("BTCUSDT", 2.0) is False
    assert await engine._refresh_execution_market("BTCUSDT") is True
    assert engine.market_data.is_fresh("BTCUSDT", 2.0) is True
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


async def test_ready_rejects_synthetic_runtime_even_when_process_is_running(database):
    import httpx

    from crypto_trader.api.app import create_app
    from crypto_trader.config import Settings
    from crypto_trader.runtime.bootstrap import build_system

    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=True,
        paper_mode="PAPER_SYNTHETIC",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    await bundle.engine.start("ready-synthetic-rejected")
    bundle.app_state.llm_runtime.provider = "deepseek"
    bundle.app_state.llm_runtime.model = "test-model"
    bundle.app_state.llm_runtime.configured = True
    bundle.app_state.llm_runtime.reachable = True
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(bundle.app_state)),
            base_url="http://test",
        ) as client:
            response = await client.get("/ready")
        assert response.status_code == 503
        payload = response.json()
        assert payload["ready"] is False
        assert "PAPER_REAL_MARKET_REQUIRED" in payload["reasons"]
        assert "OKX_PUBLIC_MARKET_NOT_READY" in payload["reasons"]
    finally:
        await bundle.engine.stop()
        await bundle.database.close()
