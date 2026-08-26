import asyncio
from datetime import UTC, datetime, timedelta

from crypto_trader.runtime.ai_position_bridge import AIPositionRuntimeBridge


def active_position(**overrides):
    base = {
        "quantity": 1.0,
        "side": "LONG",
        "thesis_status": "THESIS_INTACT",
        "thesis": "trend",
        "entry_price": 100.0,
        "current_price": 105.0,
        "unrealized_pnl": 5.0,
        "realized_pnl": 0.0,
        "age_seconds": 3600,
        "hard_risk_exit": False,
        "requested_change": 0.3,
    }
    base.update(overrides)
    return base


def test_bridge_routes_active_position():
    bridge = AIPositionRuntimeBridge()
    evaluation = bridge.evaluate(symbol="BTC-USDT", active_position=active_position())
    assert evaluation.action == "HOLD"
    assert evaluation.executable is False


def test_bridge_exit_when_invalidated():
    bridge = AIPositionRuntimeBridge()
    evaluation = bridge.evaluate(
        symbol="BTC-USDT", active_position=active_position(thesis_status="THESIS_INVALIDATED")
    )
    assert evaluation.action == "EXIT"
    assert evaluation.executable is True
    assert evaluation.side == "SELL"
    assert evaluation.quantity == 1.0


def test_bridge_reduce_quantity_capped():
    bridge = AIPositionRuntimeBridge()
    evaluation = bridge.evaluate(
        symbol="BTC-USDT",
        active_position=active_position(thesis_status="THESIS_WEAKENING", requested_change=5.0),
    )
    assert evaluation.action == "REDUCE"
    assert evaluation.quantity <= 1.0


def test_bridge_cooldown_prevents_duplicate_decision():
    bridge = AIPositionRuntimeBridge(cooldown_seconds=5.0)
    now = datetime.now(UTC)
    bridge.evaluate(symbol="BTC-USDT", active_position=active_position(), now=now)
    second = bridge.evaluate(
        symbol="BTC-USDT", active_position=active_position(), now=now + timedelta(seconds=1)
    )
    assert second.action == "COOLDOWN"


async def test_supervisor_ai_position_loop_runs_callback(database):
    from crypto_trader.runtime.lease import LeaseManager
    from crypto_trader.runtime.supervisor import TradingRuntimeSupervisor

    leases = LeaseManager(database.session_factory)
    calls = []

    async def cb():
        calls.append(1)

    supervisor = TradingRuntimeSupervisor(
        lease_manager=leases,
        interval_seconds=0.01,
        renew_interval=3600,
        execution_interval=3600,
        ai_position_callback=cb,
        ai_position_interval_seconds=0.02,
    )
    await supervisor.start()
    await asyncio.sleep(0.08)
    await supervisor.stop()
    assert len(calls) >= 1
