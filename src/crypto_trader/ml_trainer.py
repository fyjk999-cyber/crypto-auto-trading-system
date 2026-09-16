# ruff: noqa: B905
# Deterministic chronological walk-forward trainer for ML evidence models.
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

FEATURES = (
    "l1_imbalance",
    "l5_imbalance",
    "microprice_deviation",
    "spread_bps",
    "cvd_ratio",
    "relative_volume",
    "oi_change_pct",
    "funding_rate",
    "price_change_24h_pct",
)


def extract_features(f: dict) -> dict:
    price = f.get("price")
    micro = f.get("microprice")
    dev = (micro - price) / price if micro and price else None
    tb, ts = f.get("taker_buy_volume"), f.get("taker_sell_volume")
    tot = (tb or 0.0) + (ts or 0.0)
    cvd_ratio = (f.get("cvd") / tot) if f.get("cvd") is not None and tot > 0 else None
    taker = ((tb - ts) / tot) if tb is not None and ts is not None and tot > 0 else None
    return {
        "l1_imbalance": f.get("l1_imbalance"),
        "l5_imbalance": f.get("l5_imbalance"),
        "microprice_deviation": dev,
        "spread_bps": f.get("spread_bps"),
        "cvd_ratio": cvd_ratio,
        "relative_volume": f.get("relative_volume"),
        "oi_change_pct": f.get("oi_change_pct"),
        "funding_rate": f.get("funding_rate"),
        "price_change_24h_pct": f.get("price_change_24h_pct"),
        "taker_imbalance": taker,
    }


ALL_FEATURES = FEATURES + ("taker_imbalance",)


def build_samples(frozen: dict, horizon: str, direction: str, min_edge_bps: float) -> list:
    labels = {
        row["snapshot_id"]: row for row in frozen.get("labels", []) if row.get("horizon") == horizon
    }
    samples = []
    for snap in frozen.get("snapshots", []):
        row = labels.get(snap.get("snapshot_id"))
        if row is None:
            continue
        net = row.get("long_net_bps") if direction == "LONG" else row.get("short_net_bps")
        if net is None:
            continue
        samples.append(
            {
                "ts": snap.get("captured_at"),
                "features": extract_features(snap.get("features") or {}),
                "label": 1 if net > min_edge_bps else 0,
                "net_bps": net,
            }
        )
    return sorted(samples, key=lambda x: x["ts"])


def make_folds(samples: list, n_folds: int = 3, min_train: int = 20, min_valid: int = 5) -> list:
    """Expanding-window folds with max(train_ts) < min(valid_ts)."""
    n = len(samples)
    folds = []
    if n < min_train + min_valid:
        return folds
    block = max(min_valid, n // (n_folds + 1))
    for i in range(1, n_folds + 1):
        train_end = block * i
        valid_end = min(n, train_end + block)
        if train_end < min_train or valid_end <= train_end:
            break
        train, valid = samples[:train_end], samples[train_end:valid_end]
        if not (train[-1]["ts"] < valid[0]["ts"]):
            continue
        folds.append(
            {
                "train": train,
                "valid": valid,
                "max_train_ts": train[-1]["ts"],
                "min_valid_ts": valid[0]["ts"],
            }
        )
    return folds


def _median(values: list):
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return 0.0
    mid = len(clean) // 2
    return clean[mid] if len(clean) % 2 else (clean[mid - 1] + clean[mid]) / 2.0


def fit_preprocessing(rows: list) -> dict:
    medians = {name: _median([r["features"].get(name) for r in rows]) for name in ALL_FEATURES}
    imputed = [
        [
            (r["features"].get(n) if r["features"].get(n) is not None else medians[n])
            for n in ALL_FEATURES
        ]
        for r in rows
    ]
    means = (
        [sum(col) / max(1, len(col)) for col in zip(*imputed)]
        if imputed
        else [0.0] * len(ALL_FEATURES)
    )
    stds = []
    for idx, col in enumerate(zip(*imputed) if imputed else []):
        var = sum((v - means[idx]) ** 2 for v in col) / max(1, len(col))
        stds.append(math.sqrt(var) or 1.0)
    return {"medians": medians, "means": means, "stds": stds or [1.0] * len(ALL_FEATURES)}


def vectorize(row: dict, prep: dict) -> list:
    out = [1.0]
    for idx, name in enumerate(ALL_FEATURES):
        value = row["features"].get(name)
        if value is None:
            value = prep["medians"][name]
        out.append((float(value) - prep["means"][idx]) / prep["stds"][idx])
    return out


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def fit_logistic(
    vectors: list, labels: list, epochs: int = 300, lr: float = 0.3, l2: float = 0.01
) -> list:
    weights = [0.0] * len(vectors[0]) if vectors else []
    for _ in range(epochs):
        grads = [0.0] * len(weights)
        for x, y in zip(vectors, labels):
            err = sigmoid(sum(w * v for w, v in zip(weights, x))) - y
            for j, v in enumerate(x):
                grads[j] += err * v
        scale = lr / max(1, len(vectors))
        for j in range(len(weights)):
            weights[j] -= scale * (grads[j] + l2 * weights[j])
    return weights


def auc_score(labels: list, probs: list) -> float:
    positives = [p for y, p in zip(labels, probs) if y == 1]
    negatives = [p for y, p in zip(labels, probs) if y == 0]
    if not positives or not negatives:
        return 0.5
    wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in positives for b in negatives)
    return wins / (len(positives) * len(negatives))


def prf(labels: list, probs: list, threshold: float = 0.5) -> dict:
    tp = sum(1 for y, p in zip(labels, probs) if y == 1 and p >= threshold)
    fp = sum(1 for y, p in zip(labels, probs) if y == 0 and p >= threshold)
    fn = sum(1 for y, p in zip(labels, probs) if y == 1 and p < threshold)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = sum(1 for y, p in zip(labels, probs) if (p >= threshold) == (y == 1)) / max(
        1, len(labels)
    )
    return {"precision": precision, "recall": recall, "f1": f1, "directional_accuracy": accuracy}


def walk_forward_train(
    samples: list,
    output_dir,
    *,
    horizon: str,
    direction: str,
    min_edge_bps: float,
    n_folds: int = 3,
    min_train: int = 20,
    min_valid: int = 5,
    model_id: str = "21_ORDER_FLOW_ML",
    code_sha: str = "",
    dataset_version: str = "",
    feature_version: str = "scan-features-v1",
    label_version: str = "label-v1",
) -> dict:
    folds = make_folds(samples, n_folds=n_folds, min_train=min_train, min_valid=min_valid)
    if len(folds) < 2:
        return {"status": "INSUFFICIENT_FOLDS", "fold_count": len(folds), "samples": len(samples)}
    pooled_labels, pooled_probs, pooled_net = [], [], []
    fold_records = []
    for fold in folds:
        prep = fit_preprocessing(fold["train"])
        weights = fit_logistic(
            [vectorize(r, prep) for r in fold["train"]], [r["label"] for r in fold["train"]]
        )
        probs = [
            sigmoid(sum(w * v for w, v in zip(weights, vectorize(r, prep)))) for r in fold["valid"]
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
                "auc": auc_score(labels, probs),
                **prf(labels, probs),
            }
        )
    pooled_metrics = {
        "auc": auc_score(pooled_labels, pooled_probs),
        **prf(pooled_labels, pooled_probs),
        "oos_samples": len(pooled_probs),
        "horizon": horizon,
        "direction": direction,
        "fold_count": len(folds),
        "mean_net_bps_valid": sum(pooled_net) / max(1, len(pooled_net)),
    }
    prep_all = fit_preprocessing(samples)
    weights_all = fit_logistic(
        [vectorize(r, prep_all) for r in samples], [r["label"] for r in samples]
    )
    metrics = {"walk_forward": pooled_metrics, "folds": fold_records}
    artifact = {
        "model_id": model_id,
        "feature_version": feature_version,
        "label_version": label_version,
        "features": list(ALL_FEATURES),
        "hyperparameters": {"epochs": 300, "lr": 0.3, "l2": 0.01, "n_folds": n_folds},
        "preprocessing": prep_all,
        "weights": weights_all,
        "metrics": metrics,
        "training_window": {"rows": len(samples)},
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
    path = out / f"{model_id}-{version}.json"
    if not path.exists():
        path.write_bytes(blob)
    chronological = all(f["max_train_ts"] < f["min_valid_ts"] for f in fold_records)
    return {
        "status": "OK",
        "model_version": version,
        "artifact_path": str(path),
        "artifact_hash": digest,
        "metrics": metrics,
        "chronological": chronological,
        "fold_count": len(fold_records),
    }
