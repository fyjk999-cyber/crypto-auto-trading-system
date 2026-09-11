import httpx
import pytest
from sqlalchemy import select

from crypto_trader.api.app import create_app
from crypto_trader.config import Settings
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.errors import LeaseNotHeld
from crypto_trader.domain.models import SignalIntent
from crypto_trader.persistence.models import EngineRunORM
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
        "factor_snapshot",
        "factor_history",
        "factor_performance",
    }.issubset(bundle.position_manager.tool_chief.tools.available())
    assert bundle.position_manager.__class__.__name__ == "LiveLLMPositionManager"
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
