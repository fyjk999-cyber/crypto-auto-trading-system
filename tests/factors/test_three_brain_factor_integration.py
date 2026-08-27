import asyncio

from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.factors.version import FactorSetVersion
from crypto_trader.llm.tools.live_factor_tools import LiveFactorTools


def candles(n=30):
    rows = []
    for i in range(n):
        c = 100 + i * 0.5
        rows.append(
            {
                "open": str(c - 0.2),
                "high": str(c + 0.3),
                "low": str(c - 0.4),
                "close": str(c),
                "volume": str(100 + i),
            }
        )
    return rows


def test_gateway_calculates_versioned_snapshot():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        candles=candles(),
        market_data={"bid_volume": "60", "ask_volume": "40"},
    )
    assert snapshot.factor_set_version == "factorset-v1"
    assert snapshot.factor("trend") is not None
    assert snapshot.snapshot_id


def test_snapshot_immutability():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(
        symbol="BTC-USDT-SWAP", timeframe="15m", candles=candles()
    )
    import pytest

    with pytest.raises((AttributeError, TypeError)):
        snapshot.factors[0].metadata["x"] = "y"


def test_valid_zero_vs_failure_distinction():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(symbol="BTC-USDT-SWAP", timeframe="15m", candles=[])
    # failed factors recorded, not silently zero
    assert snapshot.failed_factors


def test_critical_factor_missing_candles_no_fake_zero():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(symbol="BTC-USDT-SWAP", timeframe="15m", candles=[])
    trend = snapshot.factor("trend")
    assert trend is None or snapshot.failed_factors


def test_factor_profile_selection_and_versions():
    gateway = FactorToolGateway(factor_set=FactorSetVersion.active_default())
    assert gateway.get_active_factor_set().version.status == "ACTIVE"
    gateway2 = FactorToolGateway()
    assert gateway2.get_active_factor_set().version.factor_set_version == "factorset-v1"


def test_live_llm_factor_tools_read_only_and_mutation_denied():
    async def run():
        gateway = FactorToolGateway()
        tools = LiveFactorTools(gateway)
        snapshot = await tools.get_factor_snapshot("BTC-USDT-SWAP", "15m", candles())
        assert snapshot.ok is True
        version = await tools.get_active_factor_set_version()
        assert version.data["status"] == "ACTIVE"
        denied = await tools.set_factor_weight("momentum", "0.1")
        assert denied.error == "MUTATION_DENIED_LIVE_RUNTIME"
        denied2 = await tools.modify_factor_formula("momentum")
        assert denied2.error == "MUTATION_DENIED_LIVE_RUNTIME"

    asyncio.run(run())


def test_evolution_offline_does_not_break_gateway():
    # No evolution imports needed; gateway works standalone.
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(
        symbol="BTC-USDT-SWAP", timeframe="15m", candles=candles()
    )
    assert snapshot.snapshot_id
