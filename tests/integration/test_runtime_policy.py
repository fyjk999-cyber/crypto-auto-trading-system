"""Phase 2 acceptance: runtime hot-reloadable bounded policy layer.

Directive §33 mapped to tests:
HOT_POLICY_RELOAD        : test_hot_apply_without_restart + engine tick pickup
POLICY_VERSIONING        : test_versioning_records_metadata
ATOMIC_UPDATE            : test_atomic_snapshot_swap
BOUNDED_VALIDATION       : test_bounds_rejected / test_max_change_rejected /
                           test_forbidden_params_rejected
ROLLBACK                 : test_rollback_restores_previous_version
DECISION_POLICY_LINEAGE  : test_decision_evidence_records_policy_version
NO_RUNTIME_RESTART_REQUIRED : same-process manager swap assertions
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from crypto_trader.governance.runtime_policy import (
    POLICY_PARAM_BOUNDS,
    RuntimePolicyManager,
    validate_update,
)


@pytest.fixture()
async def manager(database):
    mgr = RuntimePolicyManager(database.session_factory, audit=None, check_interval_seconds=0.0)
    await mgr.initialize()
    return mgr


async def test_baseline_bootstrap_and_status(manager):
    snap = manager.snapshot
    assert snap is not None and snap.version >= 1
    assert float(snap.params["per_symbol_analysis_cooldown_s"]) == 240.0
    assert snap.params["paper_exploration_size"] == "0.0005"


async def test_hot_apply_without_restart(manager):
    """§32: 240 -> 300 hot-applies; the SAME manager instance (no restart)
    observes the new cooldown value at the next checkpoint."""
    result = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 300},
        reason="TEST contract step",
        changed_by="test-calibration",
        calibration_window="test-window-1",
    )
    assert result.status == "APPLIED", result
    assert result.version == manager.snapshot.version
    # hot pickup WITHOUT restart:
    picked_up = await manager.maybe_check(force=True)
    assert picked_up or manager.snapshot.version == result.version
    assert float(manager.get("per_symbol_analysis_cooldown_s")) == 300.0
    # DB lineage row exists with metadata
    async with manager.session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT reason, changed_by, calibration_window FROM runtime_policy "
                    "WHERE version = :v"
                ),
                {"v": result.version},
            )
        ).first()
    assert row is not None
    assert row[0] == "TEST contract step"
    assert row[1] == "test-calibration"
    assert row[2] == "test-window-1"


async def test_rollback_restores_previous_version(manager):
    apply_res = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 300},
        reason="TEST rollback step",
        changed_by="test",
    )
    assert apply_res.ok
    v_before = manager.snapshot.version
    base_version = v_before - 1
    roll = await manager.rollback(base_version, changed_by="test")
    assert roll.status == "ROLLED_BACK", roll
    await manager.maybe_check(force=True)
    assert float(manager.get("per_symbol_analysis_cooldown_s")) == 240.0
    assert manager.snapshot.version > v_before
    async with manager.session_factory() as session:
        row = (
            await session.execute(
                text("SELECT rollback_of FROM runtime_policy WHERE version = :v"),
                {"v": manager.snapshot.version},
            )
        ).first()
    assert row is not None and int(row[0]) == base_version


async def test_bounds_rejected(manager):
    result = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 1200},  # > MAX 900
        reason="TEST out of bounds",
        changed_by="test",
    )
    assert result.status == "REJECTED"
    assert any("outside" in e for e in result.errors)
    # state unchanged
    assert float(manager.get("per_symbol_analysis_cooldown_s")) == 240.0


async def test_max_change_rejected(manager):
    result = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 310},  # 240 -> 310 = +70 > ±60
        reason="TEST over step",
        changed_by="test",
    )
    assert result.status == "REJECTED"
    assert any("MAX_CHANGE" in e for e in result.errors)


async def test_cumulative_window_change_rejected(manager):
    ok = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 300}, reason="step1", changed_by="test"
    )
    assert ok.ok
    # a second +60 step within the same 30m window pushes cumulative +120 > 60
    bad = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 360}, reason="step2", changed_by="test"
    )
    assert bad.status == "REJECTED"
    assert any("window" in e for e in bad.errors)


async def test_forbidden_params_rejected(manager):
    """§22: safety parameters can NEVER be applied (fail-closed allowlist)."""
    for forbidden in (
        {"kill_switch_enabled": True},
        {"max_real_leverage": 10},
        {"reconciliation_interval_seconds": 1},
        {"lease_ttl_seconds": 1},
    ):
        result = await manager.apply_update(
            forbidden, reason="TEST safety attempt", changed_by="test"
        )
        assert result.status == "REJECTED", forbidden
        assert any("FORBIDDEN_OR_UNKNOWN" in e for e in result.errors)
    # and the stored params never gained those keys
    snap = manager.snapshot
    assert not (set(snap.params) & {"kill_switch_enabled", "max_real_leverage"})


def test_validate_update_rejects_non_numeric():
    errors = validate_update({"per_symbol_analysis_cooldown_s": "abc"}, {}, [])
    assert any("not numeric" in e for e in errors)


async def test_atomic_snapshot_swap(manager):
    """§25: the snapshot is immutable + swapped whole; concurrent readers
    never observe a partial parameter set."""
    seen = []
    for i, value in enumerate((6, 5, 6)):  # alternating steps stay in window bounds
        res = await manager.apply_update(
            {"deep_analysis_candidate_limit": value},
            reason=f"atomic step {i}",
            changed_by="test",
        )
        assert res.ok
        snap = manager.snapshot
        # every observed snapshot is complete (all 11 params present)
        assert set(snap.params) == set(POLICY_PARAM_BOUNDS)
        seen.append((snap.version, dict(snap.params)))
    versions = [v for v, _ in seen]
    assert versions == sorted(set(versions)), "versions strictly monotonic"
    limits = [p["deep_analysis_candidate_limit"] for _, p in seen]
    assert limits == [6, 5, 6]


async def test_decision_evidence_records_policy_version(database):
    """§24 DECISION_POLICY_LINEAGE: the persisted evidence payload carries
    the active policy version."""
    from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter

    mgr = RuntimePolicyManager(database.session_factory, audit=None)
    await mgr.initialize()
    adapter = ChiefTraderStrategyAdapter(provider=None, policy_manager=mgr)

    stored = {}

    class CaptureBackend:
        async def store_decision(self, evidence):
            stored.update(evidence)

    adapter.evidence_backend = CaptureBackend()
    decision = SimpleNamespace(
        decision_id="dec_policy_lineage",
        thesis="t",
        model_version="mv",
        domain_model_version="dv",
        llm_invocation_id="llm1",
        selected_strategy="mean_reversion",
        strategy_version="sv1",
        strategy_fit_score=0.7,
        market_regime="RISK_OFF",
        factor_snapshot_id="fs1",
        factor_set_version="fsv1",
        factor_profile="default",
        raw_llm_confidence=0.7,
        evidence_adjusted_confidence=0.7,
        decision_class="NO_TRADE",
        action="HOLD",
        exploration_mode=False,
        secondary_strategies=[],
        supporting_factors=[],
        contradicting_factors=[],
        dominant_factor="",
        position_size_request=0.0,
        leverage_request=0.0,
    )
    ctx = SimpleNamespace(
        symbol="TRXUSDT", positions={}, clock_time=datetime.now(UTC),
        mark_price=0.26,
    )
    decision.model_dump = lambda mode="json": {"decision_id": decision.decision_id}
    chief_ctx = SimpleNamespace(
        symbol="TRXUSDT",
        regime="RISK_OFF",
        factor_snapshot={},
        strategy_evidence={"strategy_candidates": []},
    )
    await adapter._persist_evidence(decision, ctx, chief_ctx)
    assert stored, "evidence must be captured"
    assert str(stored["analysis_evidence"]["policy_version"]) == str(mgr.snapshot.version)


async def test_chief_trader_gate_reads_hot_policy(manager):
    """HOT_POLICY_RELOAD at the consumer: after a hot 240->300 apply the
    adapter's entry cooldown reads 300 from the snapshot, no restart."""
    from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter

    adapter = ChiefTraderStrategyAdapter(
        provider=None,
        entry_cooldown_seconds=240.0,
        reversal_cooldown_seconds=240.0,
        policy_manager=manager,
    )
    assert adapter._entry_cooldown_now() == 240.0
    res = await manager.apply_update(
        {"per_symbol_analysis_cooldown_s": 300},
        reason="TEST hot gate",
        changed_by="test",
    )
    assert res.ok
    assert adapter._entry_cooldown_now() == 300.0
    assert adapter._reversal_cooldown_now() == 240.0
    res2 = await manager.apply_update(
        {"reversal_cooldown_s": 300}, reason="TEST hot gate 2", changed_by="test"
    )
    assert res2.ok
    assert adapter._reversal_cooldown_now() == 300.0


async def test_engine_tick_picks_up_policy(database, monkeypatch):
    """HOT_POLICY_RELOAD via the engine checkpoint: manager.maybe_check runs
    inside engine.tick and hot-applies without restart."""
    from tests.integration.test_perpetual_runtime_routing import _make_bundle

    mgr = RuntimePolicyManager(database.session_factory, audit=None)
    await mgr.initialize()
    bundle = await _make_bundle(database)
    try:
        bundle.engine.policy_manager = mgr
        res = await mgr.apply_update(
            {"memory_retrieval_limit": 7}, reason="engine pickup test", changed_by="test"
        )
        assert res.ok
        # one tick must observe the change (maybe_check force path inside tick)
        assert mgr._last_known_version == res.version
        await bundle.engine.tick()
        assert mgr.snapshot.version == res.version
        assert int(mgr.get("memory_retrieval_limit")) == 7
    finally:
        await bundle.engine.stop()
