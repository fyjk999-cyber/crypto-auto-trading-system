"""M6: Model #25 must be literal XGBoost (no logistic substitution)."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import xgboost as xgb

from crypto_trader import ml_meta
from crypto_trader.ml_registry import ModelRegistry


def _evidence(model_id: str, i: int) -> dict:
    return {
        "model_id": model_id,
        "model_version": "1.0",
        "family": "ORDER_FLOW" if "ORDER" in model_id else "TREND",
        "direction": "LONG" if i % 2 == 0 else "SHORT",
        "score": 0.3 if i % 2 == 0 else -0.3,
        "confidence": 0.7,
        "available": True,
    }


def _frozen(n=140):
    from crypto_trader.factors.expert.types import REQUIRED_MODEL_IDS

    model_ids = [m for m in REQUIRED_MODEL_IDS if m != "25_META_FORECAST"]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    snaps, labels = [], []
    for i in range(n):
        sid = f"s{i}"
        net = 40.0 if i % 2 == 0 else -20.0
        snaps.append(
            {
                "snapshot_id": sid,
                "captured_at": (start + timedelta(minutes=i)).isoformat(),
                "candidate": i % 2 == 0,
                "control": i % 2 == 1,
                "market_regime": "TREND" if i % 2 == 0 else "RANGE",
                "scanner_rank": (i % 10) + 1,
                "features": {
                    "model_evidence": [_evidence(mid, i) for mid in model_ids],
                    "price_change_24h_pct": 1.0 if i % 2 == 0 else -1.0,
                    "relative_volume": 1.2,
                    "spread_bps": 5.0,
                    "trade_notional_window_usd": 1_000_000.0,
                    "costs": {"total_cost_bps": 22.0},
                    "price": 100.0,
                },
            }
        )
        labels.append(
            {
                "snapshot_id": sid,
                "horizon": "15m",
                "label_version": "label-v2",
                "long_net_bps": net,
                "short_net_bps": -net,
            }
        )
    return {"snapshots": snaps, "labels": labels}


def _registry_with_valid_21(tmp_path) -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "registry.json")
    artifact = tmp_path / "m21.json"
    artifact.write_text("{}")
    registry.register(
        model_id="21_ORDER_FLOW_ML",
        model_version="v1",
        artifact_path=str(artifact),
        artifact_hash="h1",
        feature_version="order-flow-v2",
        label_version="label-v2",
        state="SHADOW",
    )
    return registry


def test_25_is_literal_xgboost_with_versioned_contract(tmp_path) -> None:
    registry = _registry_with_valid_21(tmp_path)
    result = ml_meta.train_meta_forecast(
        _frozen(),
        tmp_path,
        registry=registry,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        min_train=20,
        min_valid=5,
        dataset_version="ds-m6",
        dataset_hash="dhash-m6",
    )
    assert result["status"] == "OK", result
    assert result["algorithm"] == "XGBoost"
    assert result["xgboost_version"] == xgb.__version__
    assert result["chronological"] is True
    assert result["fold_count"] >= 2
    metadata = json.loads(Path(result["artifact_path"]).read_text())
    assert metadata["algorithm"] == ml_meta.ALGORITHM_25
    assert metadata["xgboost_version"] == xgb.__version__
    assert metadata["label_version"] == "label-v2"
    assert metadata["feature_schema_hash"] == ml_meta.feature_schema_hash()
    assert len(metadata["features"]) == len(ml_meta.META_FEATURES)
    assert "weights" not in metadata  # logistic artifact marker must be absent
    model_path = Path(metadata["xgboost_model_path"])
    assert model_path.exists()
    booster = xgb.Booster()
    booster.load_model(str(model_path))
    assert booster is not None
    entry = registry.get("25_META_FORECAST", result["model_version"])
    assert entry is not None
    assert entry["xgboost_version"] == xgb.__version__
    assert entry["algorithm"] == ml_meta.ALGORITHM_25
    assert entry["feature_schema_hash"] == result["feature_schema_hash"]


def test_25_source_uses_xgb_train_not_logistic() -> None:
    source = inspect.getsource(ml_meta)
    assert "xgboost" in source
    assert "xgb.train" in source
    assert "fit_logistic" not in source
    assert "scikit" not in source.lower()


def test_25_training_inputs_require_frozen_01_24_evidence() -> None:
    frozen = _frozen()
    frozen["snapshots"][0]["features"] = {"price": 100.0}
    rows = ml_meta.build_meta_samples(frozen, "15m", "LONG", 0.0)
    assert len(rows) == 139
    assert all("model21_prob" in row["features"] for row in rows)
    assert all("score_21_ORDER_FLOW_ML" in row["features"] for row in rows)


def test_25_pyproject_pins_xgboost_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "pyproject.toml").read_text()
    assert "xgboost==" in pyproject
