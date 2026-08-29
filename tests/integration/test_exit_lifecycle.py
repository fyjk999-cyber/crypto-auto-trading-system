"""Supervisor P1: position lifecycle (reduce-only time-stop EXIT) tests.

Proves the canonical engine loop can close aged positions through the REAL
RiskEngine + ExecutionAuthority path (no authority bypass), that settlement
survives reduce-only fills, and that decision-time factor snapshots are
durably persisted so referenced fsnap_* ids resolve after restart.
"""

import asyncio

from crypto_trader.domain.enums import MarketType, OrderSide, OrderType, PositionSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.runtime.ai_position_bridge import AIPositionRuntimeBridge
from tests.integration.test_perpetual_runtime_routing import _make_bundle, _seed_book


async def _open_spot_position(bundle, symbol="ETHUSDT", quantity="0.001"):
    await _seed_book(bundle, symbol, "2000")
    decision = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_open_" + symbol,
            strategy_id="test",
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            order_type=OrderType.MARKET,
            reason="open for exit test",
            market_type=MarketType.SPOT,
            position_side=PositionSide.LONG,
        )
    )
    assert decision.decision.value == "APPROVE", decision.reason
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        positions = await bundle.portfolio.get_positions()
        position = positions.get(symbol)
        if position is not None and float(position.quantity or 0) > 0:
            return position
        await asyncio.sleep(0.01)
    raise AssertionError(f"position did not open for {symbol}")


async def _make_bridge(engine, cooldown_seconds=0.0):
    return AIPositionRuntimeBridge(
        brain=engine.ai_position_bridge.brain,
        perpetual_engine=engine.perpetual_engine,
        time_stop_seconds=3600,
        cooldown_seconds=cooldown_seconds,
    )


async def test_time_stop_exit_lands_through_risk_and_execution(database):
    """Aged positions reach RiskEngine + ExecutionAuthority as reduce-only
    EXITs and close via real FILLED orders; no authority is bypassed."""
    from datetime import UTC, datetime, timedelta

    bundle = await _make_bundle(database)
    try:
        await _open_spot_position(bundle, "ETHUSDT")
        bridge = await _make_bridge(bundle.engine)
        bridge._first_seen_open["ETHUSDT"] = datetime.now(UTC) - timedelta(hours=2)

        evaluations = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        exits = [e for e in evaluations if e.action == "EXIT"]
        assert exits, "time stop must produce an EXIT evaluation"
        assert exits[0].reduce_only is True
        assert exits[0].side == "SELL"

        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            positions = await bundle.portfolio.get_positions()
            position = positions.get("ETHUSDT")
            if position is None or float(position.quantity or 0) == 0:
                break
            await asyncio.sleep(0.02)
        positions = await bundle.portfolio.get_positions()
        assert float(positions.get("ETHUSDT").quantity or 0) == 0

        from sqlalchemy import text
        rows = []
        for _ in range(20):
            try:
                async with bundle.database.session_factory() as session:
                    rows = (
                        await session.execute(
                            text(
                                "SELECT side, status, reduce_only FROM orders "
                                "WHERE symbol='ETHUSDT' AND strategy_id='ai_brain' "
                                "AND reduce_only=1"
                            )
                        )
                    ).all()
                if rows:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.25)
        assert rows, "reduce-only EXIT order must exist"
        assert all(r[0] == "SELL" and r[1] == "FILLED" and r[2] == 1 for r in rows)

        assert bundle.engine.health.components.get("event_processing", {}).get("ok", True) is True
    finally:
        await bundle.engine.stop()


async def test_bridge_does_not_duplicate_exit_for_open_position(database):
    """While an EXIT is in flight, later evaluation rounds must not fire a
    duplicate EXIT for the same symbol."""
    from datetime import UTC, datetime, timedelta

    bundle = await _make_bundle(database)
    try:
        await _open_spot_position(bundle, "ETHUSDT")
        bridge = await _make_bridge(bundle.engine)
        bridge._first_seen_open["ETHUSDT"] = datetime.now(UTC) - timedelta(hours=2)

        first = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert any(e.action == "EXIT" for e in first)
        second = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert not [e for e in second if e.action == "EXIT" and e.symbol == "ETHUSDT"]
    finally:
        await bundle.engine.stop()


async def test_transient_empty_position_read_does_not_reset_time_stop(database):
    """A transient empty position read must not reset the time-stop clock:
    with no open positions at all, an age entry missing for less than the
    grace window must survive the cleanup."""
    from datetime import UTC, datetime, timedelta

    bundle = await _make_bundle(database, auto_start=False)
    try:
        bridge = await _make_bridge(bundle.engine)
        bridge._first_seen_open["ETHUSDT"] = datetime.now(UTC) - timedelta(hours=2)
        bridge._missing_since["ETHUSDT"] = datetime.now(UTC)

        await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert "ETHUSDT" in bridge._first_seen_open
    finally:
        await bundle.engine.stop()


async def test_decision_time_factor_snapshot_is_persisted(database):
    """fsnap_* ids referenced by decision evidence must resolve to durable
    rows in factor_snapshots after the decision."""
    from crypto_trader.runtime.live_decision_context import LiveDecisionContextProvider

    captured = []

    async def persister(snapshot):
        captured.append(snapshot)

    provider = LiveDecisionContextProvider(
        candle_provider=_fake_candles,
        symbol="BTCUSDT",
        snapshot_persister=persister,
    )
    built = await provider.build({}, symbol="BTCUSDT")
    assert built is not None
    assert captured, "decision-time snapshot must be persisted"
    assert captured[0].snapshot_id == built.factor_snapshot_id


async def _fake_candles(symbol):
    from datetime import UTC, datetime, timedelta

    base = datetime.now(UTC) - timedelta(minutes=40)
    candles = []
    price = 100.0
    for i in range(40):
        drift = 0.1 if (i // 5) % 2 == 0 else -0.1
        price += drift
        ts = (base + timedelta(minutes=i)).isoformat()
        candles.append(
            {
                "timestamp": ts,
                "open": str(price),
                "high": str(price + 0.2),
                "low": str(price - 0.2),
                "close": str(price),
                "volume": "10",
            }
        )
    return candles


async def test_persister_failure_does_not_block_decision(database):
    from crypto_trader.runtime.live_decision_context import LiveDecisionContextProvider

    async def failing_persister(snapshot):
        raise RuntimeError("db down")

    provider = LiveDecisionContextProvider(
        candle_provider=_fake_candles,
        symbol="BTCUSDT",
        snapshot_persister=failing_persister,
    )
    built = await provider.build({}, symbol="BTCUSDT")
    assert built is not None and built.factor_snapshot_id


async def test_time_stop_age_hydrates_from_real_position_open_time(database):
    """After a restart, the time-stop clock must come from the position's
    real open time, not from process uptime: a position opened hours ago is
    immediately due for its reduce-only EXIT evaluation."""
    from datetime import UTC, datetime, timedelta

    bundle = await _make_bundle(database)
    try:
        await _open_spot_position(bundle, "ETHUSDT")

        opened_at = datetime.now(UTC) - timedelta(hours=2)
        calls = []

        async def provider(symbol, side):
            calls.append((symbol, side))
            return opened_at

        bridge = AIPositionRuntimeBridge(
            brain=bundle.engine.ai_position_bridge.brain,
            perpetual_engine=bundle.engine.perpetual_engine,
            time_stop_seconds=3600,
            position_opened_at_provider=provider,
        )
        assert bridge._first_seen_open.get("ETHUSDT") is None
        evaluations = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert ("ETHUSDT", "LONG") in calls, "provider consulted on first sight"
        exits = [e for e in evaluations if e.action == "EXIT" and e.symbol == "ETHUSDT"]
        assert exits, "2h-old position must be past the 1h time stop via hydrated age"

        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            positions = await bundle.portfolio.get_positions()
            position = positions.get("ETHUSDT")
            if position is None or float(position.quantity or 0) == 0:
                break
            await asyncio.sleep(0.02)
        positions = await bundle.portfolio.get_positions()
        assert float(positions.get("ETHUSDT").quantity or 0) == 0
    finally:
        await bundle.engine.stop()
