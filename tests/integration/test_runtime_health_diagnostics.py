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
