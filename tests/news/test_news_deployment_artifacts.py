from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crypto_trader.news.config import NewsConfig, NewsProviderConfig
from crypto_trader.news.models import ProviderHealth, SourceClass
from crypto_trader.news.providers import FetchResult, NewsProvider
from crypto_trader.news.repository import NewsRepository
from crypto_trader.news.worker import NewsWorker

ROOT = Path(__file__).resolve().parents[2]


class FailingProvider(NewsProvider):
    kind = "FAKE"

    async def fetch_since(self, cursor):
        return FetchResult(
            health=ProviderHealth.NETWORK_ERROR,
            error="simulated network down",
            fetched_at=datetime.now(UTC),
        )


def _provider_config(provider_id: str = "p1") -> NewsProviderConfig:
    return NewsProviderConfig(
        provider_id=provider_id,
        kind="FAKE",
        url="https://example.com/feed",
        source_name="Example",
        source_domain="example.com",
        source_type="RSS_NEWS",
        source_class=SourceClass.ESTABLISHED_NEWS,
    )


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh unavailable")
def test_news_launchd_artifacts_exist_and_are_evidence_only():
    plist = ROOT / "deploy" / "launchagents" / "com.lowrisk.news.plist"
    script = ROOT / "scripts" / "run_news_macos.sh"
    worker = ROOT / "scripts" / "news_worker.py"
    assert plist.exists()
    assert script.exists()
    assert worker.exists()
    text = plist.read_text()
    assert "com.lowrisk.news" in text
    assert "NEWS_ENABLED" in text
    assert "LIVE" not in text
    assert "manual-orders" not in text
    script_text = script.read_text()
    assert "scripts/news_worker.py" in script_text
    assert "PYTHONPATH" in script_text
    assert "ML_PYTHON" in script_text
    assert "NEWS_DB_PATH" in script_text
    assert "__PYTHON__" not in script_text
    assert "__REPO__" not in script_text
    syntax = subprocess.run(
        ["/bin/zsh", "-n", str(script)], capture_output=True, text=True
    )
    assert syntax.returncode == 0, syntax.stderr


async def test_worker_heartbeat_advances_and_circuit_breaker_engages(database, tmp_path):
    config = NewsConfig(
        enabled=True,
        news_dir=str(tmp_path / "news"),
        max_items_per_cycle=5,
        provider_circuit_errors=3,
        provider_max_backoff_seconds=600,
    )
    repository = NewsRepository(database.session_factory)
    worker = NewsWorker(
        database.session_factory,
        config,
        providers=[FailingProvider(_provider_config("p1"))],
        repository=repository,
        code_sha="test_sha",
    )
    for _ in range(4):
        await worker.run_once()
    heartbeat = json.loads((tmp_path / "news" / "news_heartbeat.json").read_text())
    assert heartbeat["cycles_started"] == 4
    assert heartbeat["runtime_sha"] == "test_sha"
    assert heartbeat["is_order"] is False
    assert heartbeat["authority"] == "EVIDENCE_ONLY"
    assert heartbeat["last_error"] is None

    state = await repository.get_provider_state("p1")
    assert state is not None
    assert state.status == ProviderHealth.DISABLED
    assert state.consecutive_errors >= 3
    assert state.next_retry_at is not None
    assert state.next_retry_at > datetime.now(UTC)
