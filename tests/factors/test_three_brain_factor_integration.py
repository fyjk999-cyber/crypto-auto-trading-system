import asyncio
import json
from dataclasses import FrozenInstanceError

import pytest

from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.factors.version import (
    FactorSetVersion,
    FactorSnapshotContract,
    FactorSnapshotEntry,
)
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


def _nested_snapshot() -> FactorSnapshotContract:
    return FactorSnapshotContract(
        snapshot_id="fsnap-test",
        timestamp_utc="2026-08-27T00:00:00+00:00",
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        factor_set_version="factorset-v1",
        factor_registry_version="registry-v1",
        factor_config_hash="cfg-v1",
        factors=(
            FactorSnapshotEntry(
                factor_name="trend",
                raw_value="1",
                normalized_value="1",
                confidence="0.9",
                effective_weight="1.0",
                contribution="0.1",
                status="OK",
                metadata={"nested": {"items": ["a", "b"]}},
            ),
        ),
        market_regime="TREND",
        market_data_version="v1",
        source_timestamp="2026-08-27T00:00:00+00:00",
        disabled_factors=(),
        failed_factors=(),
        calculation_warnings=(),
    )


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


def test_top_level_mutation_fails():
    snapshot = _nested_snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.symbol = "ETH-USDT-SWAP"


def test_factor_entry_mutation_fails():
    snapshot = _nested_snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.factors[0].raw_value = "2"


def test_metadata_mutation_fails():
    snapshot = _nested_snapshot()
    with pytest.raises(TypeError):
        snapshot.factors[0].metadata["new"] = "value"
    with pytest.raises(TypeError):
        snapshot.factors[0].metadata["nested"]["new"] = "value"
    with pytest.raises(AttributeError):
        snapshot.factors[0].metadata["nested"]["items"].append("c")


def test_to_dict_returns_ordinary_serializable_structures():
    snapshot = _nested_snapshot()
    payload = snapshot.to_dict()

    assert isinstance(payload["factors"], list)
    assert isinstance(payload["factors"][0]["metadata"], dict)
    assert isinstance(payload["factors"][0]["metadata"]["nested"], dict)
    assert isinstance(payload["factors"][0]["metadata"]["nested"]["items"], list)
    json.dumps(payload)


def test_to_dict_mutation_does_not_mutate_original_snapshot():
    snapshot = _nested_snapshot()
    payload = snapshot.to_dict()

    payload["factors"][0]["metadata"]["nested"]["items"].append("changed")
    payload["disabled_factors"].append("trend")

    assert snapshot.factors[0].metadata["nested"]["items"] == ("a", "b")
    assert snapshot.disabled_factors == ()


def test_snapshot_construction_copies_and_freezes_inputs():
    factor_metadata = {"nested": {"items": ["a"]}}
    factors = [
        {
            "factor_name": "trend",
            "raw_value": "1",
            "normalized_value": "1",
            "confidence": "0.9",
            "effective_weight": "1.0",
            "contribution": "0.1",
            "status": "OK",
            "metadata": factor_metadata,
        }
    ]
    disabled = ["funding"]
    failed = ["open_interest"]
    warnings = ["STALE_INPUT"]

    snapshot = FactorSnapshotContract(
        snapshot_id="fsnap-copy",
        timestamp_utc="2026-08-27T00:00:00+00:00",
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        factor_set_version="factorset-v1",
        factor_registry_version="registry-v1",
        factor_config_hash="cfg-v1",
        factors=factors,
        market_regime="TREND",
        market_data_version="v1",
        source_timestamp="2026-08-27T00:00:00+00:00",
        disabled_factors=disabled,
        failed_factors=failed,
        calculation_warnings=warnings,
    )

    factors.append({"factor_name": "late"})
    factor_metadata["nested"]["items"].append("changed")
    disabled.append("trend")
    failed.append("momentum")
    warnings.append("CALCULATION_FAILED")

    assert len(snapshot.factors) == 1
    assert snapshot.factors[0].metadata["nested"]["items"] == ("a",)
    assert snapshot.disabled_factors == ("funding",)
    assert snapshot.failed_factors == ("open_interest",)
    assert snapshot.calculation_warnings == ("STALE_INPUT",)


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
