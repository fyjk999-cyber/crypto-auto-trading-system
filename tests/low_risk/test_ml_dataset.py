# ruff: noqa: E402, ASYNC240
from datetime import UTC, datetime, timedelta

from crypto_trader import ml_dataset
from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM


def _snap(i, ts, symbol="BTCUSDT", cand=True, features=None):
    return ScanSnapshotORM(
        snapshot_id=f"s{i}",
        captured_at=ts,
        cycle_id="c1",
        symbol=symbol,
        candidate=cand,
        control=not cand,
        features_json=features
        or {
            "price": 100.0,
            "l1_imbalance": 0.1,
            "l5_imbalance": 0.2,
            "microprice": 100.01,
            "cvd": 1.0,
            "l10_imbalance": None,
        },
    )


async def test_empty_dataset_not_ready(database):
    q = await ml_dataset.evaluate_data_quality(database.session_factory)
    assert q.total == 0 and q.candidates == 0 and q.controls == 0
    r = await ml_dataset.evaluate_readiness(database.session_factory)
    assert r.ready is False
    assert any(x.startswith("insufficient_snapshots") for x in r.reasons)


async def test_readiness_ready_with_thresholds(database, monkeypatch):
    monkeypatch.setattr(ml_dataset, "MIN_SNAPSHOTS", 2)
    monkeypatch.setattr(ml_dataset, "MIN_CANDIDATES", 1)
    monkeypatch.setattr(ml_dataset, "MIN_CONTROLS", 1)
    monkeypatch.setattr(ml_dataset, "MIN_SYMBOLS", 2)
    monkeypatch.setattr(ml_dataset, "MIN_LABELED", 1)
    monkeypatch.setattr(ml_dataset, "MIN_COVERAGE_DAYS", 0)
    now = datetime.now(UTC)
    async with database.session_factory() as s:
        s.add(_snap(1, now))
        s.add(_snap(2, now, symbol="ETHUSDT", cand=False))
        s.add(
            ScanSnapshotLabelORM(
                snapshot_id="s1",
                symbol="BTCUSDT",
                snapshot_ts=now,
                horizon="1m",
                matured_at=now,
                long_net_bps=10.0,
                short_net_bps=-10.0,
            )
        )
        await s.commit()
    r = await ml_dataset.evaluate_readiness(database.session_factory)
    assert r.ready is True, r.reasons
    assert r.quality["total"] == 2 and r.quality["label_counts"] == {"1m": 1}


from pathlib import Path


async def test_freeze_versioning_and_immutability(database, tmp_path):
    now = datetime.now(UTC)
    async with database.session_factory() as s:
        s.add(_snap(1, now))
        await s.commit()
    one = await ml_dataset.freeze_dataset(database.session_factory, tmp_path, code_sha="abc")
    assert one["dataset_version"].startswith("ds-")
    p = Path(one["path"])
    assert p.exists()
    stamp = p.stat().st_mtime_ns
    two = await ml_dataset.freeze_dataset(database.session_factory, tmp_path, code_sha="abc")
    assert two["dataset_version"] == one["dataset_version"]
    assert p.stat().st_mtime_ns == stamp
    async with database.session_factory() as s:
        s.add(_snap(2, now + timedelta(minutes=1)))
        await s.commit()
    three = await ml_dataset.freeze_dataset(database.session_factory, tmp_path, code_sha="abc")
    assert three["dataset_version"] != one["dataset_version"]
