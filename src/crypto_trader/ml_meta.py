# ruff: noqa: B905
# Model #25 literal XGBoost meta forecast (EVIDENCE_ONLY; gated by valid #21).
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import xgboost as xgb

from crypto_trader import ml_trainer
from crypto_trader.factors.expert.types import REQUIRED_MODEL_IDS
from crypto_trader.ml_registry import ModelRegistry

MODEL_25_ID = "25_META_FORECAST"
MODEL_21_ID = "21_ORDER_FLOW_ML"
MIN_EDGE_BPS = 10.0
ALGORITHM_25 = "xgboost_binary_logistic_v1"
FEATURE_VERSION_25 = "meta-xgb-v2"
DEFAULT_XGBOOST_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 3,
    "eta": 0.1,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "min_child_weight": 2.0,
    "lambda": 1.0,
    "seed": 0,
    "nthread": 1,
}
NUM_BOOST_ROUND = 60

MODEL_01_24 = tuple(model_id for model_id in REQUIRED_MODEL_IDS if model_id != MODEL_25_ID)

_AGGREGATE_FEATURES = (
    "n_long",
    "n_short",
    "n_neutral",
    "n_unavailable",
    "mean_score",
    "mean_confidence",
    "disagreement",
    "effective_families",
    "model21_prob",
    "model21_available",
    "regime_trend",
    "regime_range",
    "regime_high_vol",
    "regime_uncertain",
    "cost_total_bps",
    "relative_volume",
    "spread_bps",
    "trade_notional_log",
    "evidence_quality_score",
    "degraded_reason_count",
    "scanner_rank_norm",
    "is_candidate",
)

META_FEATURES = tuple(
    [
        *_AGGREGATE_FEATURES,
        *(f"score_{model_id}" for model_id in MODEL_01_24),
        *(f"confidence_{model_id}" for model_id in MODEL_01_24),
        *(f"available_{model_id}" for model_id in MODEL_01_24),
    ]
)


def feature_schema_hash() -> str:
    return hashlib.sha256(json.dumps(list(META_FEATURES)).encode()).hexdigest()


def can_train_25(registry: ModelRegistry) -> bool:
    """#25 may train only after a valid #21 SHADOW/ACTIVE artifact exists."""
    for model in registry.data["models"]:
        if model["model_id"] != MODEL_21_ID:
            continue
        if model["state"] not in ("SHADOW", "ACTIVE"):
            continue
        if not model.get("artifact_path") or not Path(model["artifact_path"]).exists():
            continue
        label_version = str(model.get("label_version") or "")
        if label_version and label_version != "label-v2":
            continue
        return True
    return False


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def _float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _regime_flags(snapshot: dict) -> dict[str, float]:
    regime = str(
        snapshot.get("market_regime")
        or (snapshot.get("features") or {}).get("market_regime")
        or "UNCERTAIN"
    ).upper()
    return {
        "regime_trend": 1.0 if regime in {"TREND", "TRENDING"} else 0.0,
        "regime_range": 1.0 if regime in {"RANGE", "RANGING", "MEAN_REVERT"} else 0.0,
        "regime_high_vol": 1.0 if "VOL" in regime else 0.0,
        "regime_uncertain": 1.0 if regime in {"UNCERTAIN", "UNKNOWN", ""} else 0.0,
    }


def meta_features(snapshot: dict, model21_prob: float | None = None) -> dict:
    """Build the frozen #25 meta feature row from decision-time facts only."""
    features = snapshot.get("features") or {}
    evidence = features.get("model_evidence") or []
    by_id: dict[str, dict] = {}
    scores: list[float] = []
    confidences: list[float] = []
    families: set[str] = set()
    long = short = neutral = unavailable = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id") or "")
        direction = str(item.get("direction") or "").upper()
        if direction == "UNAVAILABLE" or item.get("available") is False:
            unavailable += 1
        elif direction in ("LONG", "UP", "BULLISH"):
            long += 1
        elif direction in ("SHORT", "DOWN", "BEARISH"):
            short += 1
        else:
            neutral += 1
        score = _float(item.get("score"))
        if score is None:
            score = _float(item.get("direction_score"))
        confidence = _float(item.get("confidence"))
        if score is not None:
            scores.append(score)
        if confidence is not None:
            confidences.append(confidence)
        families.add(str(item.get("family") or "other"))
        if model_id:
            by_id[model_id] = item
    directional = long + short
    disagreement = abs(long - short) / directional if directional else 0.0
    effective_families = float(len({name for name in families if name}))
    row: dict[str, float | None] = {
        "n_long": float(long),
        "n_short": float(short),
        "n_neutral": float(neutral),
        "n_unavailable": float(unavailable),
        "mean_score": _mean(scores),
        "mean_confidence": _mean(confidences),
        "disagreement": float(disagreement),
        "effective_families": effective_families,
        "model21_prob": float(model21_prob) if model21_prob is not None else None,
        "model21_available": 1.0 if model21_prob is not None else 0.0,
        **_regime_flags(snapshot),
        "cost_total_bps": float(((features.get("costs") or {}) or {}).get("total_cost_bps") or 0.0),
        "relative_volume": _float(features.get("relative_volume")),
        "spread_bps": _float(features.get("spread_bps")),
        "trade_notional_log": math.log1p(
            max(0.0, _float(features.get("trade_notional_window_usd")) or 0.0)
        ),
        "evidence_quality_score": 1.0 if features.get("evidence_quality") == "HEALTHY" else 0.0,
        "degraded_reason_count": float(len(features.get("evidence_degraded_reasons") or [])),
        "scanner_rank_norm": (
            1.0 / float(snapshot["scanner_rank"]) if snapshot.get("scanner_rank") else 0.0
        ),
        "is_candidate": 1.0 if snapshot.get("candidate") else 0.0,
    }
    for model_id in MODEL_01_24:
        item = by_id.get(model_id) or {}
        score = _float(item.get("score"))
        if score is None:
            score = _float(item.get("direction_score"))
        confidence = _float(item.get("confidence"))
        row[f"score_{model_id}"] = score if score is not None else 0.0
        row[f"confidence_{model_id}"] = confidence if confidence is not None else 0.0
        row[f"available_{model_id}"] = 1.0 if item.get("available") is True else 0.0
    return row


def _model21_probability(artifact: dict | None, snapshot: dict) -> float | None:
    if not artifact:
        return None
    try:
        from crypto_trader.ml_artifacts import LogisticPredictor

        return float(LogisticPredictor(artifact)(snapshot.get("features") or {}))
    except Exception:
        return None


def build_meta_samples(
    frozen: dict,
    horizon: str,
    direction: str,
    min_edge_bps: float,
    model21_artifact: dict | None = None,
    *,
    label_version: str = "label-v2",
) -> list:
    labels = {
        row["snapshot_id"]: row
        for row in frozen.get("labels", [])
        if row.get("horizon") == horizon
        and row.get("label_version", "label-v2") == label_version
    }
    out = []
    for snap in frozen.get("snapshots", []):
        row = labels.get(snap.get("snapshot_id"))
        if row is None:
            continue
        if not (snap.get("features") or {}).get("model_evidence"):
            # #25 may not train without frozen factual #01-#24 evidence.
            continue
        net = row.get("long_net_bps") if direction == "LONG" else row.get("short_net_bps")
        if net is None:
            continue
        prob = _model21_probability(model21_artifact, snap)
        out.append(
            {
                "ts": snap.get("captured_at"),
                "features": meta_features(snap, prob),
                "label": 1 if net > min_edge_bps else 0,
                "net_bps": net,
            }
        )
    return sorted(out, key=lambda x: x["ts"])


def _median(values: list) -> float:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return 0.0
    mid = len(clean) // 2
    return clean[mid] if len(clean) % 2 else (clean[mid - 1] + clean[mid]) / 2.0


def fit_preprocessing(rows: list) -> dict:
    medians = {name: _median([r["features"].get(name) for r in rows]) for name in META_FEATURES}
    imputed = [
        [
            (r["features"].get(n) if r["features"].get(n) is not None else medians[n])
            for n in META_FEATURES
        ]
        for r in rows
    ]
    means = (
        [sum(col) / max(1, len(col)) for col in zip(*imputed)]
        if imputed
        else [0.0] * len(META_FEATURES)
    )
    stds = []
    for idx, col in enumerate(zip(*imputed) if imputed else []):
        var = sum((v - means[idx]) ** 2 for v in col) / max(1, len(col))
        stds.append(math.sqrt(var) or 1.0)
    return {"medians": medians, "means": means, "stds": stds or [1.0] * len(META_FEATURES)}


def vectorize(row: dict, prep: dict) -> list:
    out: list[float] = []
    for idx, name in enumerate(META_FEATURES):
        value = row["features"].get(name)
        if value is None:
            value = prep["medians"][name]
        out.append((float(value) - prep["means"][idx]) / prep["stds"][idx])
    return out


def _matrix(rows: list, prep: dict):
    return xgb.DMatrix(
        [vectorize(row, prep) for row in rows],
        label=[row["label"] for row in rows],
        feature_names=list(META_FEATURES),
    )


def _booster(rows: list, prep: dict, params: dict | None = None, rounds: int = NUM_BOOST_ROUND):
    merged = {**DEFAULT_XGBOOST_PARAMS, **(params or {})}
    merged["seed"] = 0
    merged["nthread"] = 1
    return xgb.train(merged, _matrix(rows, prep), num_boost_round=int(rounds))


def train_meta_forecast(
    frozen: dict,
    output_dir,
    *,
    registry: ModelRegistry | None = None,
    model21_artifact: dict | None = None,
    model_21_version: str = "",
    model_21_artifact_hash: str = "",
    model_21_artifact_status: str = "",
    horizon: str = "15m",
    direction: str = "LONG",
    min_edge_bps: float = MIN_EDGE_BPS,
    n_folds: int = 3,
    min_train: int = 20,
    min_valid: int = 5,
    code_sha: str = "",
    dataset_version: str = "",
    dataset_hash: str = "",
) -> dict:
    if registry is not None and not can_train_25(registry):
        return {"status": "BLOCKED_UNTIL_MODEL_21_VALID"}
    samples = build_meta_samples(
        frozen, horizon, direction, min_edge_bps, model21_artifact, label_version="label-v2"
    )
    folds = ml_trainer.make_folds(
        samples, n_folds=n_folds, min_train=min_train, min_valid=min_valid
    )
    if len(folds) < 2:
        return {"status": "INSUFFICIENT_FOLDS", "fold_count": len(folds), "samples": len(samples)}
    pooled_labels, pooled_probs, pooled_net, fold_records = [], [], [], []
    for fold in folds:
        prep = fit_preprocessing(fold["train"])
        booster = _booster(fold["train"], prep)
        probs = [float(p) for p in booster.predict(_matrix(fold["valid"], prep))]
        labels = [r["label"] for r in fold["valid"]]
        pooled_labels += labels
        pooled_probs += probs
        pooled_net += [r["net_bps"] for r in fold["valid"]]
        fold_records.append(
            {
                "train_rows": len(fold["train"]),
                "valid_rows": len(fold["valid"]),
                "max_train_ts": fold["max_train_ts"],
                "min_valid_ts": fold["min_valid_ts"],
                "auc": ml_trainer.auc_score(labels, probs),
                **ml_trainer.prf(labels, probs),
            }
        )
    positives = sum(pooled_labels)
    walk_forward = {
        "auc": ml_trainer.auc_score(pooled_labels, pooled_probs),
        **ml_trainer.prf(pooled_labels, pooled_probs),
        "oos_samples": len(pooled_probs),
        "horizon": horizon,
        "direction": direction,
        "fold_count": len(folds),
        "mean_net_bps_valid": sum(pooled_net) / max(1, len(pooled_net)),
        "class_balance": {
            "positive": positives,
            "negative": len(pooled_labels) - positives,
        },
    }
    prep_all = fit_preprocessing(samples)
    final_booster = _booster(samples, prep_all)
    metrics = {"walk_forward": walk_forward, "folds": fold_records}
    cutoff = samples[-1]["ts"]
    schema_hash = feature_schema_hash()
    artifact_dir = Path(output_dir) / "models"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    base_metadata = {
        "model_id": MODEL_25_ID,
        "artifact_format": "canonical_xgboost_v1",
        "algorithm": ALGORITHM_25,
        "feature_version": FEATURE_VERSION_25,
        "feature_schema_hash": schema_hash,
        "label_version": "label-v2",
        "features": list(META_FEATURES),
        "hyperparameters": {
            **DEFAULT_XGBOOST_PARAMS,
            "num_boost_round": NUM_BOOST_ROUND,
        },
        "preprocessing": prep_all,
        "metrics": metrics,
        "training_window": {
            "rows": len(samples),
            "min_ts": samples[0]["ts"],
            "max_ts": samples[-1]["ts"],
        },
        "validation_windows": [
            {
                "max_train_ts": f["max_train_ts"],
                "min_valid_ts": f["min_valid_ts"],
                "train_rows": f["train_rows"],
                "valid_rows": f["valid_rows"],
            }
            for f in fold_records
        ],
        "dataset_version": dataset_version,
        "dataset_hash": dataset_hash,
        "code_sha": code_sha,
        "training_cutoff_ts": cutoff,
        "xgboost_version": xgb.__version__,
        "seed": 0,
        "model_21_version": model_21_version,
        "model_21_artifact_hash": model_21_artifact_hash,
        "model_21_artifact_status": model_21_artifact_status,
    }
    version_blob = json.dumps(base_metadata, sort_keys=True, default=str).encode()
    version = "v1-" + hashlib.sha256(version_blob).hexdigest()[:12]
    model_path = artifact_dir / f"{MODEL_25_ID}-{version}.ubj"
    final_booster.save_model(str(model_path))
    model_bytes = model_path.read_bytes()
    base_metadata["xgboost_model_path"] = str(model_path)
    base_metadata["xgboost_model_hash"] = hashlib.sha256(model_bytes).hexdigest()
    base_metadata["model_version"] = version
    metadata_path = artifact_dir / f"{MODEL_25_ID}-{version}.json"
    metadata_bytes = json.dumps(base_metadata, sort_keys=True, default=str).encode()
    metadata_path.write_bytes(metadata_bytes)
    artifact_hash = hashlib.sha256(metadata_bytes).hexdigest()
    if registry is not None:
        registry.register(
            model_id=MODEL_25_ID,
            model_version=version,
            artifact_path=str(metadata_path),
            artifact_hash=artifact_hash,
            dataset_version=dataset_version,
            dataset_hash=dataset_hash,
            feature_version=FEATURE_VERSION_25,
            feature_schema_hash=schema_hash,
            label_version="label-v2",
            code_sha=code_sha,
            algorithm=ALGORITHM_25,
            xgboost_version=xgb.__version__,
            training_cutoff_ts=cutoff,
            seed=0,
            training_window=base_metadata["training_window"],
            validation_windows=base_metadata["validation_windows"],
            hyperparameters=base_metadata["hyperparameters"],
            metrics=metrics,
            state="SHADOW",
        )
    return {
        "status": "OK",
        "algorithm": "XGBoost",
        "model_version": version,
        "artifact_path": str(metadata_path),
        "artifact_hash": artifact_hash,
        "artifact_metadata": base_metadata,
        "metrics": metrics,
        "fold_count": len(fold_records),
        "chronological": all(f["max_train_ts"] < f["min_valid_ts"] for f in fold_records),
        "feature_schema_hash": schema_hash,
        "feature_version": FEATURE_VERSION_25,
        "label_version": "label-v2",
        "training_cutoff_ts": cutoff,
        "xgboost_version": xgb.__version__,
        "seed": 0,
        "dataset_version": dataset_version,
        "dataset_hash": dataset_hash,
    }
