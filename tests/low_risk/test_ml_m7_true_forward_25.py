# ruff: noqa: ASYNC240
"""M7: true-forward #25 predictions with versioned #21 lineage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from crypto_trader import ml_meta
from crypto_trader.factors.expert.types import REQUIRED_MODEL_IDS
from crypto_trader.ml_artifacts import ArtifactResolver
from crypto_trader.ml_forward import ForwardPredictionStore
from crypto_trader.ml_registry import ModelRegistry
from crypto_trader.persistence.models import (
    MLForwardPredictionORM,
    ScanSnapshotLabelORM,
    ScanSnapshotORM,
)


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


def _registry(tmp_path) -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "registry.json")
    artifact = tmp_path / "m21.json"
    artifact.write_text("{}")
    registry.register(
        model_id="21_ORDER_FLOW_ML",
        model_version="v21",
        artifact_path=str(artifact),
        artifact_hash="h21",
        feature_version="order-flow-v2",
        label_version="label-v2",
        state="SHADOW",
    )
    return registry


def _snapshot(sid: str, ts: datetime) -> ScanSnapshotORM:
    model_ids = [m for m in REQUIRED_MODEL_IDS if m != "25_META_FORECAST"]
    return ScanSnapshotORM(
        snapshot_id=sid,
        captured_at=ts,
        cycle_id="c",
        symbol="BTCUSDT",
        candidate=True,
        control=False,
        market_regime="TREND",
        features_json={
            "model_evidence": [_evidence(mid, 0) for mid in model_ids],
            "relative_volume": 1.2,
            "spread_bps": 5.0,
            "trade_notional_window_usd": 1_000_000.0,
            "costs": {"total_cost_bps": 22.0},
            "market_regime": "TREND",
        },
    )


def _label(sid: str, ts: datetime, matured_at: datetime, status: str = "PENDING"):
    return ScanSnapshotLabelORM(
        snapshot_id=sid,
        symbol="BTCUSDT",
        snapshot_ts=ts,
        horizon="15m",
        matured_at=matured_at,
        label_version="label-v2",
        maturation_status=status,
        usable_for_training=status == "MATURE_VALID",
        long_net_bps=35.0,
        short_net_bps=-35.0,
    )


async def test_25_forward_post_cutoff_persists_lineage(database, tmp_path) -> None:
    registry = _registry(tmp_path)
    trained = ml_meta.train_meta_forecast(
        _frozen(),
        tmp_path,
        registry=registry,
        min_train=20,
        min_valid=5,
        dataset_version="ds-m7",
        dataset_hash="dhash-m7",
    )
    assert trained["status"] == "OK"
    loaded25 = ArtifactResolver(registry).resolve(ml_meta.MODEL_25_ID, trained["model_version"])
    assert loaded25 is not None

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=1)
    async with database.session_factory() as session:
        session.add(_snapshot("post-25", now))
        session.add(_label("post-25", now, now + timedelta(minutes=15)))
        await session.commit()

    def feature_builder(features):
        return ml_meta.meta_features(
            {"features": features, "market_regime": features.get("market_regime")}, None
        )

    def row_metadata(_features):
        return {
            "model21_probability": 0.55,
            "model21_version": "v21",
            "model21_artifact_hash": "h21",
        }

    store = ForwardPredictionStore(database.session_factory)
    written = await store.generate(
        model_id=ml_meta.MODEL_25_ID,
        model_version=trained["model_version"],
        artifact_hash=trained["artifact_hash"],
        training_cutoff_ts=cutoff,
        loaded_artifact=loaded25,
        feature_builder=feature_builder,
        row_metadata_builder=row_metadata,
        feature_version=trained["feature_version"],
        prediction_created_at=now,
    )
    assert written == 1
    assert (
        await store.generate(
            model_id=ml_meta.MODEL_25_ID,
            model_version=trained["model_version"],
            artifact_hash=trained["artifact_hash"],
            training_cutoff_ts=cutoff,
            loaded_artifact=loaded25,
            feature_builder=feature_builder,
            row_metadata_builder=row_metadata,
            feature_version=trained["feature_version"],
        )
        == 0
    )
    async with database.session_factory() as session:
        row = (await session.execute(select(MLForwardPredictionORM))).scalars().one()
    assert row.model_id == ml_meta.MODEL_25_ID
    assert row.model21_version == "v21"
    assert row.model21_artifact_hash == "h21"
    assert row.model21_probability == 0.55
    assert row.authority == "LEARNING_ONLY" and row.is_order is False
    assert row.state == "PENDING_OUTCOME"

    async with database.session_factory() as session:
        label = await session.scalar(
            select(ScanSnapshotLabelORM).where(ScanSnapshotLabelORM.snapshot_id == "post-25")
        )
        label.maturation_status = "MATURE_VALID"
        label.usable_for_training = True
        label.matured_at = now + timedelta(minutes=15)
        await session.commit()
    assert await store.attach_natural_outcomes() == 1
    summary = await store.summary(ml_meta.MODEL_25_ID, trained["model_version"])
    assert summary["samples"] == 1
    assert summary["mean_net_bps"] == 35.0


async def test_25_historical_replay_is_not_forward(database, tmp_path) -> None:
    registry = _registry(tmp_path)
    trained = ml_meta.train_meta_forecast(
        _frozen(),
        tmp_path,
        registry=registry,
        min_train=20,
        min_valid=5,
    )
    loaded25 = ArtifactResolver(registry).resolve(ml_meta.MODEL_25_ID, trained["model_version"])
    now = datetime.now(UTC)
    async with database.session_factory() as session:
        session.add(_snapshot("old-25", now - timedelta(days=1)))
        session.add(
            _label(
                "old-25",
                now - timedelta(days=1),
                now - timedelta(hours=23),
                status="MATURE_VALID",
            )
        )
        await session.commit()

    def feature_builder(features):
        return ml_meta.meta_features(
            {"features": features, "market_regime": features.get("market_regime")}, None
        )

    store = ForwardPredictionStore(database.session_factory)
    written = await store.generate(
        model_id=ml_meta.MODEL_25_ID,
        model_version=trained["model_version"],
        artifact_hash=trained["artifact_hash"],
        training_cutoff_ts=now - timedelta(days=2),
        loaded_artifact=loaded25,
        feature_builder=feature_builder,
        feature_version=trained["feature_version"],
    )
    assert written == 0
    assert await store.count(ml_meta.MODEL_25_ID, trained["model_version"]) == 0
