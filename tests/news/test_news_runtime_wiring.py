"""N7 real runtime wiring: News reassessment must ride the canonical engine."""

from __future__ import annotations

from crypto_trader.config import Settings
from crypto_trader.news.reassessment import NewsReassessmentRuntime
from crypto_trader.runtime.bootstrap import build_system


def _settings(database) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
    )


async def test_bootstrap_wires_news_reassessment_when_enabled(database, monkeypatch):
    monkeypatch.setenv("NEWS_ENABLED", "1")
    bundle = await build_system(_settings(database))
    assert isinstance(bundle.engine.news_reassessment_runtime, NewsReassessmentRuntime)
    assert bundle.engine.news_reassessment_runtime.service.repository.session_factory is not None
    await bundle.database.close()


async def test_bootstrap_leaves_news_reassessment_disabled_by_default(database, monkeypatch):
    monkeypatch.delenv("NEWS_ENABLED", raising=False)
    bundle = await build_system(_settings(database))
    assert bundle.engine.news_reassessment_runtime is None
    await bundle.database.close()
