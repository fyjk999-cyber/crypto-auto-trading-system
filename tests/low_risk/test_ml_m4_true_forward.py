# ruff: noqa: ASYNC240
"""M4: true-forward #21 shadow predictions, no historical replay counting."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from crypto_trader import ml_dataset, ml_forward, ml_orchestrator
from crypto_trader.ml_forward import ForwardPredictionStore
from crypto_trader.ml_orchestrator import MLOrchestrator
from crypto_trader.persistence.models import (
    MLForwardPredictionORM,
    ScanSnapshotLabelORM,
    ScanSnapshotORM,
)


def _snapshot(
    snapshot_id: str,
    ts: datetime,
    symbol: str = "BTCUSDT",
    *,
    candidate: bool = True,
) -> ScanSnapshotORM:
    return ScanSnapshotORM(
        snapshot_id=snapshot_id,
        captured_at=ts,
        cycle_id="c",
        symbol=symbol,
        candidate=candidate,
        control=not candidate,
        features_json={
            "price": 100.0,
            "microprice": 100.01,
            "spread_bps": 5.0,
            "l1_imbalance": 0.1,
            "l5_imbalance": 0.2,
            "cvd": 1.0,
            "taker_buy_volume": 5.0,
            "taker_sell_volume": 4.0,
            "relative_volume": 1.1,
        },
    )


def _label(
    snapshot_id: str,
    ts: datetime,
    *,
    matured_at: datetime,
    status: str = "PENDING",
    long_net_bps: float = 40.0,
) -> ScanSnapshotLabelORM:
    return ScanSnapshotLabelORM(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        snapshot_ts=ts,
        horizon="15m",
        matured_at=matured_at,
        label_version="label-v2",
        maturation_status=status,
        usable_for_training=status == "MATURE_VALID",
        long_net_bps=long_net_bps,
        short_net_bps=-long_net_bps,
    )


async def test_forward_store_rejects_historical_and_dedupes_post_cutoff(database) -> None:
    now = datetime.now(UTC)
    cutoff = now
    async with database.session_factory() as session:
        session.add(_snapshot("before", now - timedelta(minutes=10)))
        session.add(
            _label("before", now - timedelta(minutes=10), matured_at=now + timedelta(minutes=5))
        )
        session.add(_snapshot("after", now + timedelta(minutes=1)))
        session.add(
            _label("after", now + timedelta(minutes=1), matured_at=now + timedelta(minutes=16))
        )
        await session.commit()

    store = ForwardPredictionStore(database.session_factory)
    written = await store.generate(
        model_id="21_ORDER_FLOW_ML",
        model_version="v-test",
        artifact_hash="h",
        training_cutoff_ts=cutoff,
        predictor=lambda _features: 0.72,
        feature_version="order-flow-v2",
    )
    assert written == 1  # pre-cutoff snapshot is structurally excluded
    assert await store.generate(
        model_id="21_ORDER_FLOW_ML",
        model_version="v-test",
        artifact_hash="h",
        training_cutoff_ts=cutoff,
        predictor=lambda _features: 0.72,
        feature_version="order-flow-v2",
    ) == 0  # duplicate-safe / restart-safe
    async with database.session_factory() as session:
        rows = (await session.execute(select(MLForwardPredictionORM))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.snapshot_id == "after"
    assert row.state == "PENDING_OUTCOME"
    assert row.authority == "LEARNING_ONLY" and row.is_order is False
    assert row.prediction_created_at < row.training_cutoff_ts + timedelta(hours=1)
    assert row.probability == 0.72 and row.direction == "LONG"


async def test_forward_store_attaches_natural_outcome_only_after_maturity(database) -> None:
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=1)
    snapshot_ts = now
    matured_at = now + timedelta(minutes=15)
    async with database.session_factory() as session:
        session.add(_snapshot("fwd-1", snapshot_ts))
        session.add(_label("fwd-1", snapshot_ts, matured_at=matured_at, status="PENDING"))
        await session.commit()

    store = ForwardPredictionStore(database.session_factory)
    assert (
        await store.generate(
            model_id="21_ORDER_FLOW_ML",
            model_version="v-test",
            artifact_hash="h",
            training_cutoff_ts=cutoff,
            predictor=lambda _features: 0.7,
            feature_version="order-flow-v2",
            prediction_created_at=now,
        )
        == 1
    )
    assert (await store.summary("21_ORDER_FLOW_ML", "v-test"))["samples"] == 0

    async with database.session_factory() as session:
        label = await session.scalar(
            select(ScanSnapshotLabelORM).where(ScanSnapshotLabelORM.snapshot_id == "fwd-1")
        )
        label.maturation_status = "MATURE_VALID"
        label.usable_for_training = True
        label.matured_at = matured_at
        await session.commit()

    assert await store.attach_natural_outcomes() == 1
    summary = await store.summary("21_ORDER_FLOW_ML", "v-test")
    assert summary["samples"] == 1
    assert summary["mean_net_bps"] == 40.0
    assert summary["win_rate"] == 1.0
    assert await store.attach_natural_outcomes() == 0  # idempotent


async def test_forward_store_never_counts_already_mature_history(database) -> None:
    now = datetime.now(UTC)
    async with database.session_factory() as session:
        session.add(_snapshot("old", now - timedelta(days=1)))
        session.add(
            _label(
                "old",
                now - timedelta(days=1),
                matured_at=now - timedelta(hours=23),
                status="MATURE_VALID",
            )
        )
        await session.commit()
    store = ForwardPredictionStore(database.session_factory)
    written = await store.generate(
        model_id="21_ORDER_FLOW_ML",
        model_version="v-test",
        artifact_hash="h",
        training_cutoff_ts=now - timedelta(days=2),
        predictor=lambda _features: 0.8,
    )
    assert written == 0
    assert await store.count("21_ORDER_FLOW_ML", "v-test") == 0


async def test_orchestrator_counts_no_historical_replay_as_forward(
    database, tmp_path, monkeypatch
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    async with database.session_factory() as session:
        for i in range(90):
            snap_id = f"h{i}"
            snapshot = _snapshot(
                snap_id,
                start + timedelta(minutes=i),
                symbol=f"S{i % 3}USDT",
                candidate=i % 2 == 0,
            )
            snapshot.features_json = {
                **(snapshot.features_json or {}),
                "l1_imbalance": 0.4 if i % 2 == 0 else -0.4,
                "l5_imbalance": 0.3 if i % 2 == 0 else -0.3,
                "cvd": 5.0 if i % 2 == 0 else -5.0,
            }
            session.add(snapshot)
            session.add(
                _label(
                    snap_id,
                    start + timedelta(minutes=i),
                    matured_at=start + timedelta(minutes=i + 15),
                    status="MATURE_VALID",
                    long_net_bps=40.0 if i % 2 == 0 else -20.0,
                )
            )
        await session.commit()
    monkeypatch.setattr(ml_dataset, "MIN_SNAPSHOTS", 20)
    monkeypatch.setattr(ml_dataset, "MIN_CANDIDATES", 10)
    monkeypatch.setattr(ml_dataset, "MIN_CONTROLS", 10)
    monkeypatch.setattr(ml_dataset, "MIN_SYMBOLS", 1)
    monkeypatch.setattr(ml_dataset, "MIN_LABELED", 20)
    monkeypatch.setattr(ml_dataset, "MIN_COVERAGE_DAYS", 0)
    monkeypatch.setattr(ml_orchestrator, "MIN_EDGE_BPS", 0.0)
    orch = MLOrchestrator(database.session_factory, tmp_path, code_sha="sha-m4")
    result = await orch.run_once()
    assert result["state"] == "SHADOW_MODEL_21", result
    assert result["model_21_forward"]["total"] == 0
    assert result["model_21_forward"]["samples"] == 0
    async with database.session_factory() as session:
        rows = (await session.execute(select(MLForwardPredictionORM))).scalars().all()
    assert rows == []
    assert "samples[-50:]" not in inspect.getsource(MLOrchestrator.run_once)
    assert ml_forward.is_true_forward_method() is True
