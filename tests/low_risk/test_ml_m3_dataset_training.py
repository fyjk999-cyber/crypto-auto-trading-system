# ruff: noqa: ASYNC240
"""M3: immutable label-v2 #21 dataset and chronological artifact contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader import ml_dataset, ml_trainer
from crypto_trader.factors.expert.models import SPEC_BY_ID  # noqa: F401  (import sanity)
from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM


def _samples(n=120):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        rows.append(
            {
                "ts": (start + timedelta(minutes=i)).isoformat(),
                "features": {
                    "l1_imbalance": (i % 7) / 10,
                    "l5_imbalance": (i % 5) / 10,
                    "price": 100.0,
                    "microprice": 100.1,
                    "spread_bps": 5.0,
                    "cvd": i - 5,
                    "taker_buy_volume": 10.0,
                    "taker_sell_volume": 8.0,
                    "relative_volume": 1.2,
                    "oi_change_pct": 0.3,
                    "funding_rate": 0.0001,
                    "price_change_24h_pct": (i % 11) - 5,
                    "trade_count": 120,
                    "trade_notional_window_usd": 1_000_000.0,
                    "large_trade_count": 3,
                },
                "label": 1 if i % 3 == 0 else 0,
                "net_bps": 30.0 if i % 3 == 0 else -15.0,
            }
        )
    return rows


async def test_m3_freeze_label_v2_only_and_manifest(database, tmp_path) -> None:
    now = datetime.now(UTC)
    async with database.session_factory() as s:
        s.add(
            ScanSnapshotORM(
                snapshot_id="v2-snap",
                captured_at=now,
                cycle_id="c",
                symbol="BTCUSDT",
                candidate=True,
                control=False,
                market_regime="TREND",
                features_json={"price": 100.0, "l1_imbalance": 0.1, "l5_imbalance": 0.2},
            )
        )
        s.add(
            ScanSnapshotORM(
                snapshot_id="v1-snap",
                captured_at=now + timedelta(minutes=1),
                cycle_id="c",
                symbol="ETHUSDT",
                candidate=False,
                control=True,
                features_json={"price": 50.0},
            )
        )
        s.add(
            ScanSnapshotLabelORM(
                snapshot_id="v2-snap",
                symbol="BTCUSDT",
                snapshot_ts=now,
                horizon="15m",
                matured_at=now + timedelta(minutes=15),
                label_version="label-v2",
                maturation_status="MATURE_VALID",
                usable_for_training=True,
                long_net_bps=40.0,
                short_net_bps=-40.0,
                cost_version="cost-v1",
            )
        )
        s.add(
            ScanSnapshotLabelORM(
                snapshot_id="v1-snap",
                symbol="ETHUSDT",
                snapshot_ts=now + timedelta(minutes=1),
                horizon="15m",
                matured_at=now + timedelta(minutes=16),
                label_version="label-v1",
                long_net_bps=40.0,
                short_net_bps=-40.0,
            )
        )
        await s.commit()

    frozen = await ml_dataset.freeze_dataset(
        database.session_factory, tmp_path, code_sha="sha-m3"
    )
    assert frozen["ready"] is True
    assert frozen["label_version"] == "label-v2"
    assert frozen["row_count"] == 1
    assert frozen["exclusions"]["label_v1_excluded"] == 1
    assert frozen["feature_schema_hash"]
    assert frozen["training_cutoff_ts"]
    manifest = json.loads(Path(frozen["path"]).read_text())
    assert [row["label_version"] for row in manifest["labels"]] == ["label-v2"]
    assert {row["snapshot_id"] for row in manifest["snapshots"]} == {"v2-snap"}
    assert manifest["feature_schema_hash"] == frozen["feature_schema_hash"]
    assert manifest["code_sha"] == "sha-m3"


def test_m3_artifact_contract_and_reproducibility(tmp_path) -> None:
    samples = _samples()
    result = ml_trainer.walk_forward_train(
        samples,
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        n_folds=3,
        min_train=20,
        min_valid=5,
        code_sha="sha-m3",
        dataset_version="ds-test",
        dataset_hash="dhash",
        feature_version=ml_trainer.FEATURE_VERSION_21,
        label_version="label-v2",
    )
    assert result["status"] == "OK"
    assert result["chronological"] is True
    assert result["feature_schema_hash"] == ml_trainer.feature_schema_hash()
    assert result["training_cutoff_ts"] == samples[-1]["ts"]
    artifact = json.loads(Path(result["artifact_path"]).read_text())
    for key in (
        "model_id",
        "artifact_format",
        "algorithm",
        "feature_version",
        "feature_schema_hash",
        "label_version",
        "code_sha",
        "dataset_version",
        "dataset_hash",
        "training_cutoff_ts",
        "hyperparameters",
        "preprocessing",
        "metrics",
        "validation_windows",
    ):
        assert key in artifact, key
    assert artifact["label_version"] == "label-v2"
    assert artifact["metrics"]["walk_forward"]["class_balance"]["positive"] > 0
    assert artifact["metrics"]["walk_forward"]["fold_count"] >= 2
    for fold in artifact["metrics"]["folds"]:
        assert fold["max_train_ts"] < fold["min_valid_ts"]
    again = ml_trainer.walk_forward_train(
        samples,
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        n_folds=3,
        min_train=20,
        min_valid=5,
        code_sha="sha-m3",
        dataset_version="ds-test",
        dataset_hash="dhash",
        feature_version=ml_trainer.FEATURE_VERSION_21,
        label_version="label-v2",
    )
    assert again["model_version"] == result["model_version"]
    assert again["artifact_hash"] == result["artifact_hash"]


def test_m3_preprocessing_is_fitted_on_train_folds_only(tmp_path, monkeypatch) -> None:
    samples = _samples()
    folds = ml_trainer.make_folds(samples, n_folds=3, min_train=20, min_valid=5)
    assert len(folds) >= 2
    observed_train_sizes: list[int] = []
    original = ml_trainer.fit_preprocessing

    def spy(rows):
        observed_train_sizes.append(len(rows))
        return original(rows)

    monkeypatch.setattr(ml_trainer, "fit_preprocessing", spy)
    result = ml_trainer.walk_forward_train(
        samples,
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        n_folds=3,
        min_train=20,
        min_valid=5,
    )
    assert result["status"] == "OK"
    # First N calls are the folds; each sees only that fold's TRAIN rows. The
    # final call fits the production artifact on all chronological training rows.
    assert observed_train_sizes[: len(folds)] == [len(fold["train"]) for fold in folds]
    assert observed_train_sizes[-1] == len(samples)
    assert all(size < len(samples) for size in observed_train_sizes[: len(folds)])


def test_m3_registry_entry_matches_immutable_artifact(tmp_path) -> None:
    from crypto_trader.ml_registry import ModelRegistry

    samples = _samples()
    result = ml_trainer.walk_forward_train(
        samples,
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        code_sha="sha-m3",
        dataset_version="ds-test",
        dataset_hash="dhash",
    )
    artifact = json.loads(Path(result["artifact_path"]).read_text())
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(
        model_id=result["artifact_metadata"]["model_id"],
        model_version=result["model_version"],
        artifact_path=result["artifact_path"],
        artifact_hash=result["artifact_hash"],
        dataset_version=result["dataset_version"],
        dataset_hash=result["dataset_hash"],
        feature_version=result["feature_version"],
        feature_schema_hash=result["feature_schema_hash"],
        label_version=result["label_version"],
        code_sha=result["artifact_metadata"]["code_sha"],
        algorithm=result["artifact_metadata"]["algorithm"],
        training_cutoff_ts=result["training_cutoff_ts"],
        validation_windows=result["artifact_metadata"]["validation_windows"],
        hyperparameters=result["artifact_metadata"]["hyperparameters"],
        metrics=result["metrics"],
        state="SHADOW",
    )
    entry = registry.get("21_ORDER_FLOW_ML", result["model_version"])
    assert entry is not None
    for field in (
        "model_id",
        "dataset_version",
        "feature_version",
        "feature_schema_hash",
        "label_version",
        "algorithm",
        "training_cutoff_ts",
    ):
        expected = artifact.get(field, result.get(field))
        assert entry[field] == expected, field
    assert entry["artifact_hash"] == result["artifact_hash"]
