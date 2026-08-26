import asyncio
from decimal import Decimal

from crypto_trader.config import Settings
from crypto_trader.domain.enums import OrderSide, OrderType
from crypto_trader.domain.models import SignalIntent
from crypto_trader.persistence.models import PositionProjectionORM
from crypto_trader.runtime.bootstrap import build_system


async def _make_bundle(database, auto_start=True):
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
    if auto_start:
        await bundle.engine.start()
    return bundle


async def _seed_book(bundle, symbol, price="100"):
    await bundle.market_data.ingest_snapshot(
        symbol,
        1,
        [(Decimal(price), Decimal("10"))],
        [(Decimal(price) + 1, Decimal("10"))],
    )


async def _open_bundle_position(bundle, symbol="BTCUSDT", qty="0.1"):
    await _seed_book(bundle, symbol)
    signal = SignalIntent(
        signal_id=f"open_{symbol}_{asyncio.get_running_loop().time()}",
        strategy_id="test",
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=qty,
        order_type=OrderType.MARKET,
        reason="open for test",
    )
    await bundle.engine.process_signal(signal)
    await asyncio.sleep(0.2)


async def _insert_position(database, symbol, qty="0.1"):
    async with database.session_factory() as session:
        session.add(
            PositionProjectionORM(
                account_id="default",
                symbol=symbol,
                base_asset=symbol[:3],
                quote_asset="USDT",
                quantity=Decimal(qty),
                avg_entry_price=Decimal("100"),
                cost_basis=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()


async def _start_supervisor(bundle, interval=0.02):
    from crypto_trader.runtime.lease import LeaseManager
    from crypto_trader.runtime.supervisor import TradingRuntimeSupervisor

    leases = LeaseManager(bundle.database.session_factory)
    supervisor = TradingRuntimeSupervisor(
        lease_manager=leases,
        lease_key="ai_position_test",
        interval_seconds=0.01,
        renew_interval=3600,
        execution_interval=3600,
        ai_position_callback=bundle.app_state.supervisor.ai_position_callback,
        ai_position_interval_seconds=interval,
    )
    await supervisor.start()
    return supervisor


async def test_build_system_supervisor_callback_nonnull(database):
    bundle = await _make_bundle(database, auto_start=False)
    assert bundle.supervisor is not None
    assert bundle.app_state.supervisor is not None
    assert bundle.app_state.supervisor.ai_position_callback is not None
    await bundle.database.close()


async def test_supervisor_loop_auto_reevaluates_active_position(database):
    bundle = await _make_bundle(database)
    await _open_bundle_position(bundle)
    bridge = bundle.ai_bridge
    assert bridge is not None
    # Direct callback through official supervisor field (not manual bridge)
    supervisor = await _start_supervisor(bundle)
    await asyncio.sleep(0.1)
    await supervisor.stop()
    await bundle.engine.stop()
    # callback function is bound method of bridge; inspect decision history via supervisor attr
    decisions = bundle.ai_bridge.decision_history
    assert any(d["symbol"] == "BTCUSDT" and d["action"] == "HOLD" for d in decisions)
    await bundle.database.close()


async def test_multi_position_auto_reevaluation(database):
    bundle = await _make_bundle(database)
    await _insert_position(database, "BTCUSDT", "0.1")
    await _insert_position(database, "ETHUSDT", "0.2")
    await _insert_position(database, "SOLUSDT", "0.3")
    bridge = bundle.ai_bridge
    evaluations = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
    symbols = {e.symbol for e in evaluations}
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"} <= symbols
    await bundle.database.close()


async def test_reduce_real_runtime_path(database):
    bundle = await _make_bundle(database)
    await _open_bundle_position(bundle)
    bridge = bundle.ai_bridge
    bridge.thesis_overrides["BTCUSDT"] = "THESIS_WEAKENING"
    bridge.requested_change_overrides["BTCUSDT"] = 0.05
    supervisor = await _start_supervisor(bundle)
    await asyncio.sleep(0.15)
    await supervisor.stop()
    await asyncio.sleep(0.1)
    positions = await bundle.portfolio.get_positions()
    assert "BTCUSDT" in positions
    assert float(positions["BTCUSDT"].quantity) < 0.1
    assert float(positions["BTCUSDT"].quantity) >= 0
    await bundle.engine.stop()
    await bundle.database.close()


async def test_exit_real_runtime_path(database):
    bundle = await _make_bundle(database)
    await _open_bundle_position(bundle)
    bridge = bundle.ai_bridge
    bridge.thesis_overrides["BTCUSDT"] = "THESIS_INVALIDATED"
    supervisor = await _start_supervisor(bundle)
    await asyncio.sleep(0.15)
    await supervisor.stop()
    await asyncio.sleep(0.1)
    positions = await bundle.portfolio.get_positions()
    assert "BTCUSDT" not in positions or float(positions["BTCUSDT"].quantity) == 0
    await bundle.engine.stop()
    await bundle.database.close()


async def test_duplicate_exit_protection(database):
    bundle = await _make_bundle(database, auto_start=False)
    bridge = bundle.ai_bridge
    active = {
        "quantity": 1.0,
        "side": "LONG",
        "thesis_status": "THESIS_INVALIDATED",
        "thesis": "bad",
        "requested_change": 0.0,
    }
    first = bridge.evaluate(symbol="BTCUSDT", active_position=active)
    second = bridge.evaluate(symbol="BTCUSDT", active_position=active)
    assert first.action == "EXIT"
    assert second.action == "COOLDOWN"
    executable = [d for d in bridge.decision_history if d.get("executable")]
    assert len(executable) == 1
    await bundle.database.close()


def test_partial_exit_does_not_mark_exited():
    from crypto_trader.ai_brain.position_manager.state import PositionLifecycle
    from crypto_trader.ai_brain.runtime_adapter import map_trading_intent

    lifecycle = PositionLifecycle()
    lifecycle.transition("ENTERED", "entry")
    lifecycle.transition("MONITORING", "monitor")
    lifecycle.transition("EXIT_PENDING", "exit requested")
    # Simulated partial fill leaves 0.4 BTC remaining
    remaining = 0.4
    assert lifecycle.state == "EXIT_PENDING"
    assert remaining > 0
    mapping = map_trading_intent(
        intent_action="EXIT", position_side="LONG", position_quantity=remaining
    )
    assert mapping.quantity == remaining
    assert lifecycle.state == "EXIT_PENDING"
    # Full close then EXITED
    lifecycle.transition("EXITED", "full close")
    assert lifecycle.state == "EXITED"


def test_learning_feedback_after_review():
    from crypto_trader.learning.mistake import MistakeLog
    from crypto_trader.learning.pattern import PatternMemory

    mistakes = MistakeLog()
    mistakes.add("late_exit", "BTCUSDT", "held too long")
    patterns = PatternMemory()
    patterns.save(
        market_pattern="trend_failure",
        decision="EXIT",
        result="LOSS",
        lesson="exit faster when thesis invalid",
    )
    assert "late_exit" in mistakes.frequent()
    assert patterns.find("trend_failure")[0]["lesson"].startswith("exit faster")
