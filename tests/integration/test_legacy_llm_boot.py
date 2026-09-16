from __future__ import annotations

import httpx

from crypto_trader.api.app import create_app
from crypto_trader.config import Settings
from crypto_trader.legacy_llm.isolation import legacy_llm_enabled
from crypto_trader.runtime.bootstrap import build_system


async def test_legacy_llm_disabled_boots_paper_infrastructure_without_llm_calls(database):
    """Official boot remains healthy while the legacy boundary is disabled.

    ``auto_start_runtime=False`` selects the old non-LLM/Dummy strategy path.
    It is deliberately a PAPER_SYNTHETIC integration test: no factual market
    provider or Low-Risk V2 decision provider is contacted during this proof.
    """

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
        legacy_llm_enabled=False,
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    assert legacy_llm_enabled(settings.legacy_llm_enabled) is False

    bundle = await build_system(settings)
    assert [strategy.name for strategy in bundle.engine.strategies] == ["dummy"]

    run_id = await bundle.engine.start("legacy-llm-disabled-boot")
    assert run_id == "legacy-llm-disabled-boot"
    assert bundle.engine.health.snapshot()["components"]["adapter_connection"]["ok"] is True
    assert bundle.engine.health.snapshot()["components"]["recovery"]["ok"] is True
    assert bundle.engine.health.snapshot()["components"]["execution_lease"]["ok"] is True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(bundle.app_state)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/ready")).status_code == 200
        assert (await client.get("/health")).status_code == 200

    await bundle.engine.stop()
    await bundle.database.close()
