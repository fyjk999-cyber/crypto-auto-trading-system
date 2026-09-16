from datetime import UTC, datetime, timedelta

from crypto_trader import ml_dataset, ml_orchestrator
from crypto_trader.ml_orchestrator import MLOrchestrator
from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM


async def _seed(database, n=90, label_version="label-v2"):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    async with database.session_factory() as s:
        for i in range(n):
            sid = f"s{i}"
            s.add(
                ScanSnapshotORM(
                    snapshot_id=sid,
                    captured_at=start + timedelta(minutes=i),
                    cycle_id="c",
                    symbol=f"SYM{i % 3}USDT",
                    candidate=i % 2 == 0,
                    control=i % 2 == 1,
                    features_json={
                        "price": 100.0 + i * 0.1,
                        "microprice": 100.0 + i * 0.1 + 0.01,
                        "spread_bps": 5.0,
                        "l1_imbalance": (i % 5) / 10,
                        "l5_imbalance": (i % 7) / 10,
                        "cvd": i,
                        "taker_buy_volume": 10.0,
                        "taker_sell_volume": 8.0,
                        "relative_volume": 1.1,
                        "oi_change_pct": 0.2,
                        "funding_rate": 0.0001,
                        "price_change_24h_pct": (i % 11) - 5,
                        "model_evidence": [],
                        "costs": {"total_cost_bps": 22.0},
                    },
                    outcome_status="PENDING",
                )
            )
            s.add(
                ScanSnapshotLabelORM(
                    snapshot_id=sid,
                    symbol=f"SYM{i % 3}USDT",
                    snapshot_ts=start + timedelta(minutes=i),
                    horizon="15m",
                    matured_at=start + timedelta(minutes=i + 15),
                    feature_version="scan-features-v1",
                    label_version=label_version,
                    maturation_status="MATURE_VALID" if label_version == "label-v2" else None,
                    usable_for_training=label_version == "label-v2",
                    long_net_bps=40.0 if (i % 5) >= 3 else -20.0,
                    short_net_bps=-40.0 if (i % 5) >= 3 else 20.0,
                    long_label="PROFITABLE" if (i % 5) >= 3 else "NOT_PROFITABLE",
                    short_label="NOT_PROFITABLE",
                    all_in_cost_bps=22.0,
                )
            )
        await s.commit()


async def test_waiting_for_data_and_restart_recovery(database, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_dataset, "MIN_SNAPSHOTS", 2)
    monkeypatch.setattr(ml_dataset, "MIN_CANDIDATES", 1)
    monkeypatch.setattr(ml_dataset, "MIN_CONTROLS", 1)
    monkeypatch.setattr(ml_dataset, "MIN_SYMBOLS", 1)
    monkeypatch.setattr(ml_dataset, "MIN_LABELED", 1)
    monkeypatch.setattr(ml_dataset, "MIN_COVERAGE_DAYS", 0)
    orch = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha1")
    result = await orch.run_once()
    assert result["state"] == "WAITING_FOR_DATA"
    assert result["reasons"]
    assert (tmp_path / "state.json").exists() and (tmp_path / "trainer_heartbeat.json").exists()
    restarted = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha1")
    assert restarted.state.state == "WAITING_FOR_DATA"


async def test_autonomous_shadow_model_21_step(database, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_dataset, "MIN_SNAPSHOTS", 20)
    monkeypatch.setattr(ml_dataset, "MIN_CANDIDATES", 10)
    monkeypatch.setattr(ml_dataset, "MIN_CONTROLS", 10)
    monkeypatch.setattr(ml_dataset, "MIN_SYMBOLS", 2)
    monkeypatch.setattr(ml_dataset, "MIN_LABELED", 20)
    monkeypatch.setattr(ml_dataset, "MIN_COVERAGE_DAYS", 0)
    monkeypatch.setattr(ml_orchestrator, "MIN_EDGE_BPS", 0.0)
    await _seed(database)
    orch = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha1")
    result = await orch.run_once()
    assert result["state"] == "SHADOW_MODEL_21", result
    version = result["model_21_version"]
    assert version and orch.registry.get("21_ORDER_FLOW_ML", version)["state"] == "SHADOW"
    assert (tmp_path / "datasets").exists() and (tmp_path / "models").exists()
    assert (tmp_path / "shadow" / "predictions.jsonl").exists()
    assert result["model_25_version"] is None  # no model_evidence in seed, so #25 stays gated


async def test_label_v1_only_cannot_train_or_promote(database, tmp_path, monkeypatch):
    # OLD behavior: label-v1 rows could satisfy readiness and reach shadow training.
    # NEW behavior (M0 safety gate): label-v1 is archival only; final training stays waiting.
    monkeypatch.setattr(ml_dataset, "MIN_SNAPSHOTS", 20)
    monkeypatch.setattr(ml_dataset, "MIN_CANDIDATES", 10)
    monkeypatch.setattr(ml_dataset, "MIN_CONTROLS", 10)
    monkeypatch.setattr(ml_dataset, "MIN_SYMBOLS", 2)
    monkeypatch.setattr(ml_dataset, "MIN_LABELED", 20)
    monkeypatch.setattr(ml_dataset, "MIN_COVERAGE_DAYS", 0)
    await _seed(database, label_version="label-v1")
    orch = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha1")
    result = await orch.run_once()
    assert result["state"] == "WAITING_FOR_DATA", result
    assert any("label_v2" in reason or "label_v1" in reason for reason in result["reasons"])
    assert not (tmp_path / "models").exists() or not list((tmp_path / "models").iterdir())
    assert not (tmp_path / "datasets").exists() or not list((tmp_path / "datasets").iterdir())
