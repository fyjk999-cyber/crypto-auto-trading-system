from crypto_trader.config import Settings
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
    assert bundle.position_manager.__class__.__name__ == "LiveLLMPositionManager"
    assert not hasattr(bundle, "ai_position_bridge")
    run_id = await bundle.engine.start()
    assert run_id
    assert bundle.engine.state_machine.state.value == "RUNNING"
    assert bundle.engine.lease is not None
    await bundle.engine.stop()
    await bundle.database.close()
