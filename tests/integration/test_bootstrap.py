import httpx
import pytest
from sqlalchemy import select

from crypto_trader.api.app import create_app
from crypto_trader.config import Settings
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.errors import LeaseNotHeld
from crypto_trader.domain.models import SignalIntent
from crypto_trader.persistence.database import Database
from crypto_trader.persistence.models import EngineRunORM, NewsReassessmentEventORM
from crypto_trader.runtime.bootstrap import build_system


async def test_bootstrap_builds_and_starts_single_core(database):
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=True,
        paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    assert bundle.engine is not None
    # Quant is evidence-only; the accepted canonical entry authority is Live LLM.
    assert [strategy.name for strategy in bundle.engine.strategies] == ["live_llm"]
    assert bundle.position_manager is not None
    assert bundle.engine.position_manager is bundle.position_manager
    assert bundle.position_manager.chief is bundle.engine.strategies[0].chief
    assert bundle.position_manager.tool_chief is bundle.engine.strategies[0].tool_chief
    assert bundle.position_manager.tool_chief.chief is bundle.position_manager.chief
    assert {
        "memory_search",
        "episode_search",
        "research_retrieval",
        "coin_profile",
        "factor_intelligence",
    }.issubset(bundle.position_manager.tool_chief.tools.available())
    assert bundle.position_manager.__class__.__name__ == "LiveLLMPositionManager"
    # Phase 4D: hedge/reverse legs must use the canonical planner + durable store.
    assert bundle.position_manager.hedge_planner is not None
    assert bundle.position_manager.leg_service is not None
    assert bundle.engine.leg_service is bundle.position_manager.leg_service
    assert not hasattr(bundle, "ai_position_bridge")
    assert bundle.engine.enforce_llm_entry_authority is True
    run_id = await bundle.engine.start()
    assert run_id
    assert bundle.engine.state_machine.state.value == "RUNNING"
    assert bundle.engine.lease is not None
    result = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="quant-direct-entry",
            strategy_id="multi_strategy_alpha",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity="1",
            limit_price="101",
        )
    )
    assert result is None
    assert await bundle.order_manager.count_open() == 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(bundle.app_state)),
        base_url="http://test",
    ) as client:
        opened = await client.post(
            "/paper/perpetual/open",
            json={"side": "LONG", "quantity": "1", "price": "100"},
        )
        closed = await client.post(
            "/paper/perpetual/close",
            json={"side": "LONG", "quantity": "1", "price": "100"},
        )
    assert opened.status_code == 403
    assert opened.json()["detail"] == "NEW_DIRECTION_REQUIRES_LIVE_LLM"
    assert closed.status_code == 403
    assert closed.json()["detail"] == "POSITION_ACTION_REQUIRES_LIVE_LLM"
    await bundle.engine.stop()
    await bundle.database.close()


async def test_new_fenced_writer_closes_stale_unended_runtime_rows(database):
    async with database.session_factory() as session:
        session.add(
            EngineRunORM(
                run_id="stale-crashed-run",
                state="RUNNING",
                mode="PAPER",
                strategy_id="live_llm",
                metadata_json={"lease_key": "crypto_engine_execution"},
            )
        )
        await session.commit()

    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    await bundle.engine.start("fresh-fenced-run")

    async with database.session_factory() as session:
        rows = (
            await session.execute(select(EngineRunORM).order_by(EngineRunORM.run_id))
        ).scalars().all()
        active = [row for row in rows if row.ended_at is None]
        stale = next(row for row in rows if row.run_id == "stale-crashed-run")
    assert [row.run_id for row in active] == ["fresh-fenced-run"]
    assert stale.state == "STOPPED"
    assert stale.metadata_json["shutdown_reason"] == "STALE_RUN_RECONCILED"
    assert stale.metadata_json["recovered_by"] == "fresh-fenced-run"

    await bundle.engine.stop()
    await bundle.database.close()


async def test_failed_lease_acquisition_never_closes_other_runtime_row(database):
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
    )
    bundle = await build_system(settings)
    held = await bundle.leases.acquire(
        "crypto_engine_execution", "existing-writer", ttl_seconds=60
    )
    assert held is not None
    async with database.session_factory() as session:
        session.add(
            EngineRunORM(
                run_id="existing-runtime-row",
                state="RUNNING",
                mode="PAPER",
                strategy_id="live_llm",
                metadata_json={"lease_key": "crypto_engine_execution"},
            )
        )
        await session.commit()

    with pytest.raises(LeaseNotHeld):
        await bundle.engine.start("denied-writer")

    async with database.session_factory() as session:
        existing = await session.get(EngineRunORM, "existing-runtime-row")
    assert existing is not None and existing.ended_at is None
    assert existing.state == "RUNNING"
    await bundle.leases.release(
        held.lease_key,
        held.token,
        owner_id=held.owner_id,
        fence_generation=held.fence_generation,
    )
    await bundle.database.close()


async def test_bootstrap_reads_news_dispatch_from_dedicated_news_database(
    database, tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    news_url = f"sqlite+aiosqlite:///{tmp_path}/news-dispatch.db"
    news_db = Database(news_url)
    await news_db.init_schema()
    async with news_db.session_factory() as session:
        session.add(
            NewsReassessmentEventORM(
                request_id="newsreq-cross-db",
                event_id="news-e1",
                event_version=1,
                news_evidence_id="ev1",
                symbol="BTCUSDT",
                dedup_key="cross-db-1",
                priority="HIGH",
                materiality_tier="HIGH",
                reason="TEST_CROSS_DB",
                position_state="UNKNOWN",
                requested_at=datetime.now(UTC),
            )
        )
        await session.commit()

    monkeypatch.setenv("NEWS_ENABLED", "1")
    monkeypatch.setenv("NEWS_DATABASE_URL", news_url)
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    try:
        assert bundle.news_database is not None
        assert bundle.engine.news_reassessment_runtime is not None
        repository = bundle.engine.news_reassessment_runtime.service.repository
        pending = await repository.list_pending_reassessments(limit=10)
        assert [row["request_id"] for row in pending] == ["newsreq-cross-db"]
    finally:
        await bundle.database.close()
        if bundle.news_database is not None:
            await bundle.news_database.close()
        await news_db.close()


async def test_bootstrap_uses_dedicated_growth_database_for_memory(
    database, tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    from crypto_trader.learning.retrieval import GrowthRetriever
    from crypto_trader.persistence.models import GrowthMemoryVersionORM

    growth_url = f"sqlite+aiosqlite:///{tmp_path}/growth-memory.db"
    growth_db = Database(growth_url)
    await growth_db.init_schema()
    async with growth_db.session_factory() as session:
        session.add(
            GrowthMemoryVersionORM(
                object_type="REGIME_PATTERN",
                object_id="cross-db-pattern",
                version=1,
                available_at=datetime(2026, 9, 16, tzinfo=UTC),
                sample_count=80,
                sample_tier="CANDIDATE",
                memory_speed="PATTERN",
                quality=0.8,
                contradictions=0,
                post_cost_expectancy_bps=8.0,
                payload_json={"symbol": "BTCUSDT", "regime": "TREND_UP"},
                source_refs_json={"episodes": ["e1"]},
            )
        )
        await session.commit()

    monkeypatch.setenv("GROWTH_DATABASE_URL", growth_url)
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=True,
        paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    try:
        assert bundle.growth_database is not None
        assert bundle.position_manager is not None
        loader = bundle.position_manager.context_loader
        assert loader is not None
        assert loader.growth_session_factory is bundle.growth_database.session_factory
        result = await GrowthRetriever(loader.growth_session_factory).search(
            symbol="BTCUSDT",
            as_of_timestamp=datetime(2026, 9, 17, tzinfo=UTC),
        )
        assert result["result_count"] >= 1
        assert result["results"][0]["memory_id"] == "cross-db-pattern"
    finally:
        await bundle.engine.stop()
        await bundle.database.close()
        if bundle.growth_database is not None:
            await bundle.growth_database.close()
        await growth_db.close()
