from pathlib import Path

from crypto_trader import ml_meta
from crypto_trader.ml_registry import ModelRegistry


def _ev(i):
    return [
        {
            "model_id": f"m{j}",
            "family": f"f{j % 4}",
            "score": 0.2 if (i + j) % 2 else -0.3,
            "confidence": 0.8,
            "direction": "LONG" if (i + j) % 2 else "SHORT",
        }
        for j in range(1, 11)
    ]


def _frozen():
    snaps, labels = [], []
    for i in range(120):
        sid = f"s{i}"
        snaps.append(
            {
                "snapshot_id": sid,
                "captured_at": f"2026-01-01T00:{i:02d}:00",
                "features": {
                    "model_evidence": _ev(i),
                    "price_change_24h_pct": (i % 11) - 5,
                    "price": 100.0,
                },
            }
        )
        labels.append(
            {
                "snapshot_id": sid,
                "horizon": "15m",
                "long_net_bps": 30.0 if i % 3 == 0 else -15.0,
                "short_net_bps": -30.0 if i % 3 == 0 else 15.0,
            }
        )
    return {"snapshots": snaps, "labels": labels}


def test_25_blocked_until_valid_21(tmp_path):
    reg = ModelRegistry(tmp_path / "registry.json")
    assert ml_meta.can_train_25(reg) is False
    blocked = ml_meta.train_meta_forecast(_frozen(), tmp_path, registry=reg)
    assert blocked["status"] == "BLOCKED_UNTIL_MODEL_21_VALID"
    artifact = tmp_path / "m21.json"
    artifact.write_text("{}")
    reg.register(
        model_id="21_ORDER_FLOW_ML",
        model_version="v1",
        artifact_path=str(artifact),
        artifact_hash="h1",
        state="SHADOW",
    )
    assert ml_meta.can_train_25(reg) is True


def test_meta_training_uses_factual_decision_time_evidence(tmp_path):
    reg = ModelRegistry(tmp_path / "registry.json")
    artifact = tmp_path / "m21.json"
    artifact.write_text("{}")
    reg.register(
        model_id="21_ORDER_FLOW_ML",
        model_version="v1",
        artifact_path=str(artifact),
        artifact_hash="h1",
        state="SHADOW",
    )
    result = ml_meta.train_meta_forecast(
        _frozen(),
        tmp_path,
        registry=reg,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        min_train=20,
        min_valid=5,
    )
    assert result["status"] == "OK" and result["chronological"] is True
    assert result["fold_count"] >= 2
    entry = reg.get("25_META_FORECAST", result["model_version"])
    assert entry is not None and entry["state"] == "SHADOW"
    assert Path(result["artifact_path"]).exists()


def test_meta_samples_skip_snapshots_without_model_evidence():
    frozen = _frozen()
    frozen["snapshots"][0]["features"] = {"price": 100.0}
    rows = ml_meta.build_meta_samples(frozen, "15m", "LONG", 0.0)
    assert len(rows) == 119
    assert all("model21_prob" in r["features"] for r in rows)
    one_hour = ml_meta.build_meta_samples(
        {
            "snapshots": frozen["snapshots"],
            "labels": [
                {"snapshot_id": "s1", "horizon": "1h", "long_net_bps": 99.0, "short_net_bps": -99.0}
            ],
        },
        "15m",
        "LONG",
        0.0,
    )
    assert one_hour == []
