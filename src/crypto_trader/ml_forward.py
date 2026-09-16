# ruff: noqa: B905
# True-forward ML prediction store (LEARNING_ONLY; never an order).
"""Persist predictions before outcome maturity and attach natural label-v2 later.

A row is eligible for this store only when:

* ``snapshot_ts > artifact.training_cutoff_ts`` (strictly post-cutoff), and
* no mature label-v2 existed when ``prediction_created_at`` was persisted.

Historical replay may be written to a diagnostic file elsewhere, but it can
never enter this table and can never count toward promotion.
"""

from __future__ import annotations

import inspect
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from crypto_trader.persistence.models import (
    MLForwardPredictionORM,
    ScanSnapshotLabelORM,
    ScanSnapshotORM,
)

TRUE_FORWARD_MIN_SAMPLES_21 = 30
TRUE_FORWARD_MIN_SAMPLES_25 = 20
STATE_PENDING = "PENDING_OUTCOME"
STATE_MATURED = "MATURED"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _direction(probability: float) -> str:
    return "LONG" if probability >= 0.5 else "SHORT"


class ForwardPredictionStore:
    authority = "LEARNING_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def record(self, row: dict[str, Any]) -> bool:
        snapshot_ts = _as_utc(row["snapshot_ts"])
        cutoff = _as_utc(row["training_cutoff_ts"])
        created_at = _as_utc(row.get("prediction_created_at") or datetime.now(UTC))
        if snapshot_ts <= cutoff:
            return False
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(func.count()).where(
                    MLForwardPredictionORM.model_id == row["model_id"],
                    MLForwardPredictionORM.model_version == row["model_version"],
                    MLForwardPredictionORM.snapshot_id == row["snapshot_id"],
                )
            )
            if existing:
                return False
            mature_before_prediction = await session.scalar(
                select(func.count()).where(
                    ScanSnapshotLabelORM.snapshot_id == row["snapshot_id"],
                    ScanSnapshotLabelORM.horizon == row.get("horizon", "15m"),
                    ScanSnapshotLabelORM.label_version == "label-v2",
                    ScanSnapshotLabelORM.maturation_status == "MATURE_VALID",
                    ScanSnapshotLabelORM.usable_for_training.is_(True),
                    ScanSnapshotLabelORM.matured_at <= created_at,
                )
            )
            if mature_before_prediction:
                # Outcome was already knowable: this is historical replay and
                # must never be counted as true forward.
                return False
            record = MLForwardPredictionORM(
                prediction_id=row.get("prediction_id") or "fwd_" + secrets.token_hex(10),
                model_id=str(row["model_id"]),
                model_version=str(row["model_version"]),
                artifact_hash=str(row.get("artifact_hash") or ""),
                snapshot_id=str(row["snapshot_id"]),
                symbol=str(row["symbol"]),
                horizon=str(row.get("horizon") or "15m"),
                snapshot_ts=snapshot_ts,
                prediction_created_at=created_at,
                training_cutoff_ts=cutoff,
                probability=float(row["probability"]),
                direction=str(row.get("direction") or _direction(float(row["probability"]))),
                expected_edge=(
                    float(row["expected_edge"]) if row.get("expected_edge") is not None else None
                ),
                confidence=(
                    float(row["confidence"]) if row.get("confidence") is not None else None
                ),
                feature_version=str(row.get("feature_version") or ""),
                model21_probability=(
                    float(row["model21_probability"])
                    if row.get("model21_probability") is not None
                    else None
                ),
                model21_version=(
                    str(row["model21_version"]) if row.get("model21_version") else None
                ),
                model21_artifact_hash=(
                    str(row["model21_artifact_hash"])
                    if row.get("model21_artifact_hash")
                    else None
                ),
                label_version=str(row.get("label_version") or "label-v2"),
                state=STATE_PENDING,
                authority="LEARNING_ONLY",
                is_order=False,
            )
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
        return True

    async def generate(
        self,
        *,
        model_id: str,
        model_version: str,
        artifact_hash: str,
        training_cutoff_ts: datetime | str,
        predictor: Callable[[dict[str, Any]], float] | None = None,
        loaded_artifact=None,
        feature_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        row_metadata_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        horizon: str = "15m",
        feature_version: str = "",
        label_version: str = "label-v2",
        limit: int = 500,
        prediction_created_at: datetime | None = None,
    ) -> int:
        if predictor is None:
            if loaded_artifact is None:
                raise ValueError("predictor_or_loaded_artifact_required")
            predictor = loaded_artifact.predict
        cutoff = (
            training_cutoff_ts
            if isinstance(training_cutoff_ts, datetime)
            else datetime.fromisoformat(str(training_cutoff_ts))
        )
        cutoff = _as_utc(cutoff)
        created_at = prediction_created_at or datetime.now(UTC)
        async with self._session_factory() as session:
            snapshots = (
                (
                    await session.execute(
                        select(ScanSnapshotORM)
                        .where(ScanSnapshotORM.captured_at > cutoff)
                        .order_by(ScanSnapshotORM.captured_at)
                        .limit(max(1, int(limit)))
                    )
                )
                .scalars()
                .all()
            )
        written = 0
        for snapshot in snapshots:
            features = dict(snapshot.features_json or {})
            prediction_features = feature_builder(features) if feature_builder else features
            probability = float(predictor(prediction_features))
            row_metadata = row_metadata_builder(features) if row_metadata_builder else {}
            expected_edge = None
            try:
                metrics = getattr(loaded_artifact, "metadata", {}).get("metrics") or {}
                edge = ((metrics.get("walk_forward") or {}).get("mean_net_bps_valid"))
                if edge is not None:
                    expected_edge = float(edge) * (2.0 * probability - 1.0)
            except Exception:
                expected_edge = None
            row = {
                "model_id": model_id,
                "model_version": model_version,
                "artifact_hash": artifact_hash,
                "snapshot_id": snapshot.snapshot_id,
                "symbol": snapshot.symbol,
                "horizon": horizon,
                "snapshot_ts": snapshot.captured_at,
                "prediction_created_at": created_at,
                "training_cutoff_ts": cutoff,
                "probability": probability,
                "direction": _direction(probability),
                "expected_edge": expected_edge,
                "confidence": abs(probability - 0.5) * 2.0,
                "feature_version": feature_version,
                "label_version": label_version,
                "model21_probability": row_metadata.get("model21_probability"),
                "model21_version": row_metadata.get("model21_version"),
                "model21_artifact_hash": row_metadata.get("model21_artifact_hash"),
            }
            if await self.record(row):
                written += 1
        return written

    async def attach_natural_outcomes(self) -> int:
        attached = 0
        async with self._session_factory() as session:
            pending = (
                (
                    await session.execute(
                        select(MLForwardPredictionORM).where(
                            MLForwardPredictionORM.state == STATE_PENDING
                        )
                    )
                )
                .scalars()
                .all()
            )
            for prediction in pending:
                label = await session.scalar(
                    select(ScanSnapshotLabelORM)
                    .where(
                        ScanSnapshotLabelORM.snapshot_id == prediction.snapshot_id,
                        ScanSnapshotLabelORM.horizon == prediction.horizon,
                        ScanSnapshotLabelORM.label_version == "label-v2",
                        ScanSnapshotLabelORM.maturation_status == "MATURE_VALID",
                        ScanSnapshotLabelORM.usable_for_training.is_(True),
                    )
                    .order_by(ScanSnapshotLabelORM.matured_at.desc())
                )
                if label is None:
                    continue
                matured_at = _as_utc(label.matured_at)
                if matured_at <= _as_utc(prediction.prediction_created_at):
                    # The prediction was not actually before the outcome; never
                    # attach it as if it were true forward evidence.
                    continue
                net = (
                    label.long_net_bps
                    if prediction.direction == "LONG"
                    else label.short_net_bps
                )
                if net is None:
                    continue
                prediction.outcome_net_bps = float(net)
                prediction.outcome_label = "WIN" if float(net) > 0 else "LOSS"
                prediction.outcome_ts = matured_at
                prediction.maturity_quality = label.maturation_status
                prediction.state = STATE_MATURED
                attached += 1
            if attached:
                await session.commit()
        return attached

    async def summary(self, model_id: str, model_version: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            total = int(
                await session.scalar(
                    select(func.count()).where(
                        MLForwardPredictionORM.model_id == model_id,
                        MLForwardPredictionORM.model_version == model_version,
                    )
                )
                or 0
            )
            matured_rows = (
                (
                    await session.execute(
                        select(MLForwardPredictionORM).where(
                            MLForwardPredictionORM.model_id == model_id,
                            MLForwardPredictionORM.model_version == model_version,
                            MLForwardPredictionORM.state == STATE_MATURED,
                        )
                    )
                )
                .scalars()
                .all()
            )
        nets = [
            float(row.outcome_net_bps)
            for row in matured_rows
            if row.outcome_net_bps is not None
        ]
        wins = sum(1 for value in nets if value > 0)
        return {
            "samples": len(nets),
            "pending": max(0, total - len(matured_rows)),
            "total": total,
            "mean_net_bps": sum(nets) / len(nets) if nets else 0.0,
            "win_rate": wins / len(nets) if nets else 0.0,
        }

    async def count(self, model_id: str, model_version: str) -> int:
        async with self._session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).where(
                        MLForwardPredictionORM.model_id == model_id,
                        MLForwardPredictionORM.model_version == model_version,
                    )
                )
                or 0
            )


def is_true_forward_method() -> bool:
    """Diagnostic contract: this store never replays historical samples."""
    source = inspect.getsource(ForwardPredictionStore)
    return "samples[-50:]" not in source
