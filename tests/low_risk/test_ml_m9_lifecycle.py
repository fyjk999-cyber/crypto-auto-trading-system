# ruff: noqa: ASYNC240
"""M9: bounded autonomous retrain, auditable rollback, truthful status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from crypto_trader import ml_dataset, ml_orchestrator
from crypto_trader.ml_lifecycle import (
    assess_degradation,
    mark_degraded,
    rollback,
    should_retrain,
)
from crypto_trader.ml_orchestrator import MLOrchestrator
from crypto_trader.ml_registry import ModelRegistry
from crypto_trader.persistence.models import (
    MLForwardPredictionORM,
    ScanSnapshotLabelORM,
    ScanSnapshotORM,
)


def test_retrain_triggers_are_bounded_and_reasoned() -> None:
    assert should_retrain(new_samples=0, seconds_since_last_train=10**9)["retrain"] is False
    cooling = should_retrain(new_samples=100, seconds_since_last_train=60)
    assert cooling["retrain"] is False and "cooldown_active" in cooling["reasons"]
    ready = should_retrain(new_samples=100, seconds_since_last_train=10**9)
    assert ready["retrain"] is True and "minimum_new_data_after_cooldown" in ready["reasons"]
    assert should_retrain(
        new_samples=0, seconds_since_last_train=0, drift_detected=True
    )["retrain"] is True
    assert should_retrain(
        new_samples=0, seconds_since_last_train=0, scheduled_interval_elapsed=True
    )["retrain"] is False  # no new data -> no empty loop
    scheduled = should_retrain(
        new_samples=100, seconds_since_last_train=0, scheduled_interval_elapsed=True
    )
    assert scheduled["retrain"] is False and "cooldown_active" in scheduled["reasons"]


def test_degradation_semantics_require_enough_natural_forward() -> None:
    early = assess_degradation({"samples": 3, "mean_net_bps": -100.0})
    assert early["degraded"] is False
    degraded = assess_degradation({"samples": 50, "mean_net_bps": -12.0}, baseline_mean_net_bps=5.0)
    assert degraded["degraded"] is True
    assert degraded["drop_bps"] == 17.0


def test_rollback_is_auditable_and_never_deletes_artifacts(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(
        model_id="21_ORDER_FLOW_ML", model_version="v1", artifact_path="a", artifact_hash="h1"
    )
    registry.set_state("21_ORDER_FLOW_ML", "v1", "ACTIVE")
    registry.register(
        model_id="21_ORDER_FLOW_ML", model_version="v2", artifact_path="b", artifact_hash="h2"
    )
    registry.set_state("21_ORDER_FLOW_ML", "v2", "ACTIVE")
    mark_degraded(
        registry, "21_ORDER_FLOW_ML", "v2", reason="forward_drift", degradation_bps=18.0
    )
    restored = rollback(
        registry,
        "21_ORDER_FLOW_ML",
        reason="degradation",
        metrics={"samples": 50, "mean_net_bps": -13.0},
        candidate_version="v2",
    )
    assert restored is not None and restored["model_version"] == "v1"
    assert registry.active_version("21_ORDER_FLOW_ML") == "v1"
    rolled = registry.get("21_ORDER_FLOW_ML", "v2")
    assert rolled["state"] == "ROLLED_BACK"
    details = rolled["history"][-1]["details"]
    assert details["old_version"] == "v2"
    assert details["candidate_version"] == "v2"
    assert details["result"] == "v1"
    assert details["metrics"]["samples"] == 50
    assert details["timestamp"]
    # Both versions remain in the immutable registry/history.
    assert {m["model_version"] for m in registry.data["models"]} == {"v1", "v2"}


def test_candidate_failure_keeps_existing_active(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(model_id="m", model_version="v1", artifact_path="a", artifact_hash="h1")
    registry.set_state("m", "v1", "ACTIVE")
    registry.register(model_id="m", model_version="v2", artifact_path="b", artifact_hash="h2")
    registry.set_state("m", "v2", "VALIDATION_FAILED", reason="promotion_reject")
    assert registry.active_version("m") == "v1"
    assert registry.get("m", "v1")["state"] == "ACTIVE"


async def _seed(database, n=90):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    async with database.session_factory() as session:
        for i in range(n):
            sid = f"s{i}"
            session.add(
                ScanSnapshotORM(
                    snapshot_id=sid,
                    captured_at=start + timedelta(minutes=i),
                    cycle_id="c",
                    symbol=f"S{i % 3}USDT",
                    candidate=i % 2 == 0,
                    control=i % 2 == 1,
                    features_json={
                        "price": 100.0,
                        "microprice": 100.01,
                        "spread_bps": 5.0,
                        "l1_imbalance": 0.4 if i % 2 == 0 else -0.4,
                        "l5_imbalance": 0.3 if i % 2 == 0 else -0.3,
                        "cvd": 5.0 if i % 2 == 0 else -5.0,
                        "taker_buy_volume": 10.0,
                        "taker_sell_volume": 8.0,
                        "relative_volume": 1.1,
                        "oi_change_pct": 0.2,
                        "funding_rate": 0.0001,
                        "price_change_24h_pct": (i % 11) - 5,
                        "model_evidence": [],
                    },
                )
            )
            session.add(
                ScanSnapshotLabelORM(
                    snapshot_id=sid,
                    symbol=f"S{i % 3}USDT",
                    snapshot_ts=start + timedelta(minutes=i),
                    horizon="15m",
                    matured_at=start + timedelta(minutes=i + 15),
                    feature_version="scan-features-v1",
                    label_version="label-v2",
                    maturation_status="MATURE_VALID",
                    usable_for_training=True,
                    long_net_bps=40.0 if i % 2 == 0 else -20.0,
                    short_net_bps=-40.0 if i % 2 == 0 else 20.0,
                )
            )
        await session.commit()


async def test_repeated_runs_are_bounded_and_status_is_truthful(
    database, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(ml_dataset, "MIN_SNAPSHOTS", 20)
    monkeypatch.setattr(ml_dataset, "MIN_CANDIDATES", 10)
    monkeypatch.setattr(ml_dataset, "MIN_CONTROLS", 10)
    monkeypatch.setattr(ml_dataset, "MIN_SYMBOLS", 1)
    monkeypatch.setattr(ml_dataset, "MIN_LABELED", 20)
    monkeypatch.setattr(ml_dataset, "MIN_COVERAGE_DAYS", 0)
    monkeypatch.setattr(ml_orchestrator, "MIN_EDGE_BPS", 0.0)
    await _seed(database)
    orchestrator = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha-m9")
    first = await orchestrator.run_once()
    assert first["state"] == "SHADOW_MODEL_21", first
    model_count = len(orchestrator.registry.data["models"])
    # No new label-v2 data and cooldown active: repeated runs must evaluate the
    # existing candidate, not create rapid-fire model versions.
    second = await orchestrator.run_once()
    assert len(orchestrator.registry.data["models"]) == model_count
    assert second["state"] in {"SHADOW_MODEL_21", "VALIDATION_FAILED"}
    snapshot = orchestrator.snapshot()
    assert snapshot["authority"] == "LEARNING_ONLY" and snapshot["is_order"] is False
    assert snapshot["lifecycle_state"] == second["state"]
    assert "model_21" in snapshot and "model_25" in snapshot
    assert snapshot["closure"] == "AUTONOMOUSLY_ACCUMULATING"
    # Restart preserves state and forward bookkeeping.
    restarted = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha-m9")
    assert restarted.state.state == orchestrator.state.state
    assert restarted.snapshot()["lifecycle_state"] == snapshot["lifecycle_state"]
    async with database.session_factory() as session:
        forward_rows = (
            (await session.execute(select(MLForwardPredictionORM))).scalars().all()
        )
    assert forward_rows == []
