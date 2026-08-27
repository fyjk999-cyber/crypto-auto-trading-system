import asyncio
from datetime import UTC, datetime

import pytest

from crypto_trader.decision_replay.evidence import DecisionEvidence, DecisionEvidenceStore
from crypto_trader.evolution.daily import DailyExperiencePackage, build_attribution_v1
from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.factors.version import FactorSnapshotContract, FactorSnapshotEntry
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


def test_factor_snapshot_deep_immutability():
    entry = FactorSnapshotEntry(
        factor_name="trend",
        raw_value="1",
        normalized_value="1",
        confidence="0.8",
        effective_weight="1",
        contribution="0",
        status="OK",
        metadata={"window": "10"},
    )
    snapshot = FactorSnapshotContract(
        snapshot_id="s1",
        timestamp_utc=datetime.now(UTC).isoformat(),
        symbol="BTC",
        timeframe="15m",
        factor_set_version="v1",
        factor_registry_version="r1",
        factor_config_hash="c1",
        factors=(entry,),
        market_regime="TRENDING",
        market_data_version="m1",
        source_timestamp=datetime.now(UTC).isoformat(),
    )
    with pytest.raises((AttributeError, TypeError)):
        snapshot.factor("trend").metadata["window"] = "99"
    with pytest.raises((AttributeError, TypeError)):
        snapshot.factors = ()
    with pytest.raises((AttributeError, TypeError)):
        snapshot.factor("trend").raw_value = "9"


def test_valid_zero_vs_calculation_failed():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(symbol="BTC-USDT-SWAP", timeframe="15m", candles=[])
    assert snapshot.failed_factors
    assert "INSUFFICIENT_HISTORY" in snapshot.calculation_warnings


def test_gateway_reused_in_bootstrap(database):
    from crypto_trader.config import Settings
    from crypto_trader.runtime.bootstrap import build_system

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
    import asyncio

    async def run():
        bundle = await build_system(settings)
        assert bundle.factor_gateway is not None
        assert bundle.app_state.factor_gateway is bundle.factor_gateway
        await bundle.database.close()

    asyncio.run(run())


def test_decision_evidence_records_factor_refs():
    evidence = DecisionEvidence(
        decision_id="d1",
        timestamp_utc=datetime.now(UTC).isoformat(),
        symbol="BTC",
        timeframe="15m",
        strategy_id="llm_chief_trader",
        strategy_version="1",
        model_version="1",
        prompt_version="1",
        factor_snapshot_id="fs1",
        factor_set_version="factorset-v1",
        factor_profile="FULL",
        market_data_reference="md1",
        analysis_evidence={},
        decision={"action": "LONG"},
        risk_decision={"decision": "APPROVE"},
    )
    store = DecisionEvidenceStore()
    store.store(evidence)
    assert store.get("d1").factor_snapshot_id == "fs1"
    assert store.get("d1").factor_set_version == "factorset-v1"


def test_daily_experience_package_utc_and_attribution():
    pkg = DailyExperiencePackage(
        package_id="p1", period_id="2026-08-25", decision_ids=("d1",), factor_snapshot_ids=("fs1",)
    )
    assert pkg.period_id == "2026-08-25"
    attribution = build_attribution_v1(
        attribution_id="a1",
        review_id="r1",
        evidence={
            "decision_id": "d1",
            "factor_snapshot_id": "fs1",
            "factor_set_version": "factorset-v1",
            "factors": {"trend": "0.8"},
        },
        decision_quality="GOOD",
        outcome_quality="LOSS",
    )
    assert attribution.decision_quality == "GOOD"
    assert attribution.outcome_quality == "LOSS"
    assert "trend" in attribution.supporting_factors


def test_live_llm_factor_tools_read_only():
    async def run():
        gateway = FactorToolGateway()
        tools = LiveFactorTools(gateway)
        denied = await tools.set_factor_weight("momentum", "0.1")
        assert denied.error == "MUTATION_DENIED_LIVE_RUNTIME"
        snapshot = await tools.get_factor_snapshot("BTC-USDT-SWAP", "15m", candles())
        assert snapshot.ok is True

    asyncio.run(run())
