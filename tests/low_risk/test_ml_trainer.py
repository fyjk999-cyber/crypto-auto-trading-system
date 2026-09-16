from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader import ml_trainer


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
                },
                "label": 1 if i % 3 == 0 else 0,
                "net_bps": 30.0 if i % 3 == 0 else -15.0,
            }
        )
    return rows


def test_walk_forward_is_chronological_and_multi_fold(tmp_path):
    rows = _samples()
    folds = ml_trainer.make_folds(rows, n_folds=3, min_train=20, min_valid=5)
    assert len(folds) >= 2
    for fold in folds:
        assert fold["max_train_ts"] < fold["min_valid_ts"]
    result = ml_trainer.walk_forward_train(
        rows,
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        n_folds=3,
        min_train=20,
        min_valid=5,
    )
    assert result["status"] == "OK" and result["chronological"] is True
    assert result["fold_count"] >= 2
    assert result["metrics"]["walk_forward"]["auc"] >= 0.0
    p = Path(result["artifact_path"])
    assert p.exists()
    stamp = p.stat().st_mtime_ns
    again = ml_trainer.walk_forward_train(
        rows,
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        n_folds=3,
        min_train=20,
        min_valid=5,
    )
    assert again["model_version"] == result["model_version"]
    assert p.stat().st_mtime_ns == stamp


def test_insufficient_samples_fail_closed(tmp_path):
    result = ml_trainer.walk_forward_train(
        _samples(10),
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        min_train=20,
        min_valid=5,
    )
    assert result["status"] == "INSUFFICIENT_FOLDS"
    assert result["fold_count"] < 2


def test_build_samples_matches_horizon_and_derives_features():
    frozen = {
        "snapshots": [
            {
                "snapshot_id": "s1",
                "captured_at": "2026-01-01T00:00:00+00:00",
                "features": {
                    "price": 100.0,
                    "microprice": 101.0,
                    "spread_bps": 5.0,
                    "taker_buy_volume": 5.0,
                    "taker_sell_volume": 5.0,
                    "cvd": 2.0,
                    "l1_imbalance": 0.1,
                },
            }
        ],
        "labels": [
            {"snapshot_id": "s1", "horizon": "15m", "long_net_bps": 50.0, "short_net_bps": -50.0},
            {"snapshot_id": "s1", "horizon": "1h", "long_net_bps": 999.0, "short_net_bps": -999.0},
        ],
    }
    rows = ml_trainer.build_samples(frozen, "15m", "LONG", 10.0)
    assert len(rows) == 1 and rows[0]["label"] == 1 and rows[0]["net_bps"] == 50.0
    assert rows[0]["features"]["microprice_deviation"] == 0.01
