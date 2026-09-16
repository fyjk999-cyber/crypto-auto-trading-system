# ruff: noqa: B905
# #25 Meta Forecast pipeline (EVIDENCE_ONLY; gated behind valid #21).
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from crypto_trader import ml_trainer
from crypto_trader.ml_registry import ModelRegistry

MODEL_25_ID = "25_META_FORECAST"
MODEL_21_ID = "21_ORDER_FLOW_ML"
MIN_EDGE_BPS = 10.0


def can_train_25(registry: ModelRegistry) -> bool:
    """#25 may train only after #21 has a valid SHADOW/ACTIVE artifact."""
    for model in registry.data["models"]:
        if model["model_id"] != MODEL_21_ID:
            continue
        if model["state"] not in ("SHADOW", "ACTIVE"):
            continue
        if model.get("artifact_path") and Path(model["artifact_path"]).exists():
            return True
    return False


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def meta_features(snapshot: dict, model21_prob: float | None = None) -> dict:
    ev = (snapshot.get("features") or {}).get("model_evidence") or []
    scores, families = [], set()
    long = short = neutral = 0
    for item in ev:
        score = item.get("score")
        if score is not None:
            scores.append(float(score))
        families.add(str(item.get("family") or "other"))
        direction = str(item.get("direction") or "").upper()
        if direction in ("LONG", "UP", "BULLISH"):
            long += 1
        elif direction in ("SHORT", "DOWN", "BEARISH"):
            short += 1
        else:
            neutral += 1
    return {
        "n_long": long,
        "n_short": short,
        "n_neutral": neutral,
        "consensus": _mean(scores),
        "effective_families": float(len(families)),
        "model21_prob": model21_prob,
        "price_change_24h_pct": (snapshot.get("features") or {}).get("price_change_24h_pct"),
    }


def _model21_probability(artifact: dict | None, snapshot: dict) -> float | None:
    if not artifact:
        return None
    prep, weights = artifact["preprocessing"], artifact["weights"]
    base = ml_trainer.extract_features(snapshot.get("features") or {})
    vector = [1.0]
    for idx, name in enumerate(artifact["features"]):
        value = base.get(name)
        if value is None:
            value = prep["medians"][name]
        vector.append((float(value) - prep["means"][idx]) / prep["stds"][idx])
    return ml_trainer.sigmoid(sum(w * v for w, v in zip(weights, vector)))


META_FEATURES = (
    "n_long",
    "n_short",
    "n_neutral",
    "consensus",
    "effective_families",
    "model21_prob",
    "price_change_24h_pct",
)


def build_meta_samples(
    frozen: dict,
    horizon: str,
    direction: str,
    min_edge_bps: float,
    model21_artifact: dict | None = None,
) -> list:
    labels = {
        row["snapshot_id"]: row for row in frozen.get("labels", []) if row.get("horizon") == horizon
    }
    out = []
    for snap in frozen.get("snapshots", []):
        row = labels.get(snap.get("snapshot_id"))
        if row is None:
            continue
        if not (snap.get("features") or {}).get("model_evidence"):
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
    out = [1.0]
    for idx, name in enumerate(META_FEATURES):
        value = row["features"].get(name)
        if value is None:
            value = prep["medians"][name]
        out.append((float(value) - prep["means"][idx]) / prep["stds"][idx])
    return out


def train_meta_forecast(
    frozen: dict,
    output_dir,
    *,
    registry: ModelRegistry | None = None,
    model21_artifact: dict | None = None,
    horizon: str = "15m",
    direction: str = "LONG",
    min_edge_bps: float = MIN_EDGE_BPS,
    n_folds: int = 3,
    min_train: int = 20,
    min_valid: int = 5,
    code_sha: str = "",
    dataset_version: str = "",
) -> dict:
    if registry is not None and not can_train_25(registry):
        return {"status": "BLOCKED_UNTIL_MODEL_21_VALID"}
    samples = build_meta_samples(frozen, horizon, direction, min_edge_bps, model21_artifact)
    folds = ml_trainer.make_folds(
        samples, n_folds=n_folds, min_train=min_train, min_valid=min_valid
    )
    if len(folds) < 2:
        return {"status": "INSUFFICIENT_FOLDS", "fold_count": len(folds), "samples": len(samples)}
    pooled_labels, pooled_probs, pooled_net, fold_records = [], [], [], []
    for fold in folds:
        prep = fit_preprocessing(fold["train"])
        weights = ml_trainer.fit_logistic(
            [vectorize(r, prep) for r in fold["train"]], [r["label"] for r in fold["train"]]
        )
        probs = [
            ml_trainer.sigmoid(sum(w * v for w, v in zip(weights, vectorize(r, prep))))
            for r in fold["valid"]
        ]
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
    walk_forward = {
        "auc": ml_trainer.auc_score(pooled_labels, pooled_probs),
        **ml_trainer.prf(pooled_labels, pooled_probs),
        "oos_samples": len(pooled_probs),
        "horizon": horizon,
        "direction": direction,
        "fold_count": len(folds),
        "mean_net_bps_valid": sum(pooled_net) / max(1, len(pooled_net)),
    }
    prep_all = fit_preprocessing(samples)
    weights_all = ml_trainer.fit_logistic(
        [vectorize(r, prep_all) for r in samples], [r["label"] for r in samples]
    )
    metrics = {"walk_forward": walk_forward, "folds": fold_records}
    artifact = {
        "model_id": MODEL_25_ID,
        "feature_version": "meta-features-v1",
        "label_version": "label-v1",
        "features": list(META_FEATURES),
        "hyperparameters": {"epochs": 300, "lr": 0.3, "l2": 0.01, "n_folds": n_folds},
        "preprocessing": prep_all,
        "weights": weights_all,
        "metrics": metrics,
        "dataset_version": dataset_version,
        "code_sha": code_sha,
        "validation_windows": [
            {"max_train_ts": f["max_train_ts"], "min_valid_ts": f["min_valid_ts"]}
            for f in fold_records
        ],
    }
    blob = json.dumps(artifact, sort_keys=True).encode()
    digest = hashlib.sha256(blob).hexdigest()
    version = f"v1-{digest[:12]}"
    out = Path(output_dir) / "models"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{MODEL_25_ID}-{version}.json"
    if not path.exists():
        path.write_bytes(blob)
    if registry is not None:
        registry.register(
            model_id=MODEL_25_ID,
            model_version=version,
            artifact_path=str(path),
            artifact_hash=digest,
            dataset_version=dataset_version,
            feature_version="meta-features-v1",
            label_version="label-v1",
            code_sha=code_sha,
            training_window={"rows": len(samples)},
            validation_windows=artifact["validation_windows"],
            hyperparameters=artifact["hyperparameters"],
            metrics=metrics,
            state="SHADOW",
        )
    return {
        "status": "OK",
        "model_version": version,
        "artifact_path": str(path),
        "artifact_hash": digest,
        "metrics": metrics,
        "fold_count": len(fold_records),
        "chronological": all(f["max_train_ts"] < f["min_valid_ts"] for f in fold_records),
    }
