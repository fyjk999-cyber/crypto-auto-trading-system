# ruff: noqa: B905, ASYNC240
# Autonomous ML trainer orchestration (deterministic, restart-safe).
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader import (
    ml_artifacts,
    ml_dataset,
    ml_forward,
    ml_lifecycle,
    ml_meta,
    ml_shadow,
    ml_trainer,
)
from crypto_trader.ml_registry import ModelRegistry

MODEL_21_ID = "21_ORDER_FLOW_ML"
MODEL_25_ID = "25_META_FORECAST"
HORIZON = "15m"
DIRECTION = "LONG"
MIN_EDGE_BPS = 10.0


@dataclass
class TrainerState:
    state: str = "WAITING_FOR_DATA"
    dataset_version: str | None = None
    model_21_version: str | None = None
    model_25_version: str | None = None
    model_21_forward: dict = field(default_factory=dict)
    model_25_forward: dict = field(default_factory=dict)
    last_train_at: str | None = None
    last_attempt_at: str | None = None
    last_valid_label_count: int = 0
    last_dataset_version: str | None = None
    retrain_reasons: list = field(default_factory=list)
    last_success: str | None = None
    last_error: str | None = None
    reasons: list = field(default_factory=list)
    as_dict: dict = field(default_factory=dict)


class MLOrchestrator:
    def __init__(self, session_factory, base_dir, *, code_sha: str = "") -> None:
        self.session_factory = session_factory
        self.base_dir = Path(base_dir)
        self.code_sha = code_sha
        self.registry = ModelRegistry(self.base_dir / "registry.json")
        self.artifact_resolver = ml_artifacts.ArtifactResolver(self.registry)
        self.forward = ml_forward.ForwardPredictionStore(session_factory)
        # Legacy diagnostic replay store: never used for promotion or ACTIVE.
        self.shadow_diagnostic = ml_shadow.ShadowStore(
            self.base_dir / "shadow" / "historical_replay_diagnostic.jsonl"
        )
        self.state_path = self.base_dir / "state.json"
        self.heartbeat_path = self.base_dir / "trainer_heartbeat.json"
        self.state = TrainerState()
        if self.state_path.exists():
            self.state = TrainerState(
                **{
                    k: v
                    for k, v in json.loads(self.state_path.read_text()).items()
                    if k in TrainerState.__dataclass_fields__
                }
            )

    def _save(
        self,
        *,
        state: str,
        reasons: list | None = None,
        dataset_version: str | None = None,
        model_21_version: str | None = None,
        model_25_version: str | None = None,
        model_21_forward: dict | None = None,
        model_25_forward: dict | None = None,
        retrain_reasons: list | None = None,
        last_train_at: str | None = None,
        last_attempt_at: str | None = None,
        last_valid_label_count: int | None = None,
        last_dataset_version: str | None = None,
        last_error: str | None = None,
    ) -> dict:
        self.state.state = state
        self.state.reasons = reasons or []
        if dataset_version:
            self.state.dataset_version = dataset_version
        if model_21_version:
            self.state.model_21_version = model_21_version
        if model_25_version:
            self.state.model_25_version = model_25_version
        if model_21_forward is not None:
            self.state.model_21_forward = dict(model_21_forward)
        if model_25_forward is not None:
            self.state.model_25_forward = dict(model_25_forward)
        if retrain_reasons is not None:
            self.state.retrain_reasons = list(retrain_reasons)
        if last_train_at is not None:
            self.state.last_train_at = last_train_at
        if last_attempt_at is not None:
            self.state.last_attempt_at = last_attempt_at
        if last_valid_label_count is not None:
            self.state.last_valid_label_count = int(last_valid_label_count)
        if last_dataset_version is not None:
            self.state.last_dataset_version = last_dataset_version
        self.state.last_error = last_error
        if state not in ("WAITING_FOR_DATA",):
            self.state.last_success = datetime.now(UTC).isoformat()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(self.state.__dict__)
        self.state_path.write_text(json.dumps(payload, indent=2, default=str))
        heartbeat = {
            "pid": __import__("os").getpid(),
            "running_sha": __import__("os").environ.get("RUNNING_SHA", ""),
            "at": datetime.now(UTC).isoformat(),
            "state": state,
            "dataset_version": self.state.dataset_version,
            "model_21_version": self.state.model_21_version,
            "model_25_version": self.state.model_25_version,
            "last_success": self.state.last_success,
            "last_error": last_error,
        }
        self.heartbeat_path.write_text(json.dumps(heartbeat, indent=2))
        return payload

    def _latest_model(self, model_id: str, states: tuple[str, ...]) -> dict | None:
        models = [
            model
            for model in self.registry.data["models"]
            if model["model_id"] == model_id and model["state"] in states
        ]
        if not models:
            return None
        return sorted(models, key=lambda model: model.get("created_at", ""))[-1]

    @staticmethod
    def _seconds_since(timestamp: str | None) -> float:
        if not timestamp:
            return 0.0
        try:
            moment = datetime.fromisoformat(timestamp)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            return max(0.0, (datetime.now(UTC) - moment).total_seconds())
        except (TypeError, ValueError):
            return 0.0

    def _forward_drop(self, model_id: str) -> float:
        active = self.registry.active_entry(model_id)
        forward = (
            self.state.model_21_forward
            if model_id == MODEL_21_ID
            else self.state.model_25_forward
        )
        if not active or not forward or forward.get("samples", 0) < 1:
            return 0.0
        baseline = float(
            ((active.get("metrics") or {}).get("walk_forward") or {}).get(
                "mean_net_bps_valid", 0.0
            )
            or 0.0
        )
        return max(0.0, baseline - float(forward.get("mean_net_bps", 0.0) or 0.0))

    async def _evaluate_candidate_21(self, entry: dict, frozen: dict, retrain: dict) -> dict:
        """Update a non-retraining #21 candidate and its promotion/degradation state."""
        model_version = str(entry["model_version"])
        loaded = self.artifact_resolver.resolve(MODEL_21_ID, model_version)
        if loaded is None:
            return self._save(
                state="VALIDATION_FAILED",
                reasons=["artifact_integrity_failed"],
                dataset_version=frozen["dataset_version"],
                model_21_version=model_version,
            )
        await self.forward.attach_natural_outcomes()
        await self.forward.generate(
            model_id=MODEL_21_ID,
            model_version=model_version,
            artifact_hash=loaded.artifact_hash,
            training_cutoff_ts=loaded.training_cutoff_ts,
            loaded_artifact=loaded,
            feature_version=loaded.feature_version,
            label_version="label-v2",
        )
        summary = await self.forward.summary(MODEL_21_ID, model_version)
        reasons = list(retrain.get("reasons") or [])
        if entry.get("state") == "ACTIVE":
            degradation = ml_lifecycle.assess_degradation(summary)
            if degradation.get("degraded"):
                ml_lifecycle.mark_degraded(
                    self.registry,
                    MODEL_21_ID,
                    model_version,
                    reason=str(degradation.get("reason")),
                    degradation_bps=float(degradation.get("drop_bps", 0.0)),
                    metrics=summary,
                )
                ml_lifecycle.rollback(
                    self.registry,
                    MODEL_21_ID,
                    reason="forward_performance_degradation",
                    metrics=summary,
                    candidate_version=model_version,
                )
                return self._save(
                    state="ROLLED_BACK",
                    reasons=[*reasons, "forward_performance_degradation"],
                    dataset_version=frozen["dataset_version"],
                    model_21_version=model_version,
                    model_21_forward=summary,
                    retrain_reasons=reasons,
                )
            return self._save(
                state="MODEL_21_ACTIVE",
                reasons=[*reasons, "healthy_active"],
                dataset_version=frozen["dataset_version"],
                model_21_version=model_version,
                model_21_forward=summary,
                retrain_reasons=reasons,
            )
        decision = ml_shadow.decide_promotion(
            post_cost_passed=True,
            fold_count=int(
                ((entry.get("metrics") or {}).get("walk_forward") or {}).get("fold_count", 0)
            ),
            shadow_summary=summary,
            min_shadow=ml_forward.TRUE_FORWARD_MIN_SAMPLES_21,
            artifact_integrity=True,
            schema_compatible=True,
        )
        if decision == "PROMOTE":
            self.registry.set_state(
                MODEL_21_ID, model_version, "ACTIVE", reason="promotion_gate"
            )
            state = "MODEL_21_ACTIVE"
        elif decision == "REJECT":
            self.registry.set_state(
                MODEL_21_ID,
                model_version,
                "VALIDATION_FAILED",
                reason="promotion_reject",
                metrics=summary,
            )
            state = "VALIDATION_FAILED"
        else:
            state = "SHADOW_MODEL_21"
        return self._save(
            state=state,
            reasons=[*reasons, decision],
            dataset_version=frozen["dataset_version"],
            model_21_version=model_version,
            model_21_forward=summary,
            retrain_reasons=reasons,
        )

    def snapshot(self) -> dict:
        """Truthful ML learning status; never an order authority."""
        active_21 = self.registry.active_entry(MODEL_21_ID)
        active_25 = self.registry.active_entry(MODEL_25_ID)
        closure = "ML_CLOSURE_PASS" if active_21 and active_25 else "AUTONOMOUSLY_ACCUMULATING"
        return {
            "lifecycle_state": self.state.state,
            "running_sha": __import__("os").environ.get("RUNNING_SHA", ""),
            "dataset_version": self.state.dataset_version,
            "last_train_at": self.state.last_train_at,
            "retrain_reasons": list(self.state.reasons),
            "model_21": {
                "state": active_21["state"] if active_21 else None,
                "model_version": (
                    active_21["model_version"] if active_21 else self.state.model_21_version
                ),
                "artifact_hash": active_21["artifact_hash"] if active_21 else None,
                "dataset_version": active_21["dataset_version"] if active_21 else None,
                "forward": dict(self.state.model_21_forward),
            },
            "model_25": {
                "state": active_25["state"] if active_25 else None,
                "model_version": (
                    active_25["model_version"] if active_25 else self.state.model_25_version
                ),
                "artifact_hash": active_25["artifact_hash"] if active_25 else None,
                "dataset_version": active_25["dataset_version"] if active_25 else None,
                "algorithm": active_25.get("algorithm") if active_25 else None,
                "xgboost_version": active_25.get("xgboost_version") if active_25 else None,
                "forward": dict(self.state.model_25_forward),
            },
            "closure": closure,
            "authority": "LEARNING_ONLY",
            "is_order": False,
        }

    def _score(self, artifact: dict, sample: dict) -> float:
        vector = ml_trainer.vectorize(sample, artifact["preprocessing"])
        return ml_trainer.sigmoid(sum(w * v for w, v in zip(artifact["weights"], vector)))

    async def run_once(self) -> dict:
        readiness = await ml_dataset.evaluate_readiness(self.session_factory)
        if not readiness.ready:
            quality = await ml_dataset.evaluate_data_quality(self.session_factory)
            return self._save(
                state=(
                    "DATA_ACCUMULATING"
                    if quality.final_label_count > 0
                    else "WAITING_FOR_DATA"
                ),
                reasons=readiness.reasons,
                last_valid_label_count=quality.final_label_count,
            )
        frozen = await ml_dataset.freeze_dataset(
            self.session_factory,
            self.base_dir / "datasets",
            code_sha=self.code_sha,
            feature_version=ml_trainer.FEATURE_VERSION_21,
            horizon=HORIZON,
            direction=DIRECTION,
        )
        payload = json.loads(Path(frozen["path"]).read_text())
        samples = ml_trainer.build_samples(
            payload, HORIZON, DIRECTION, MIN_EDGE_BPS, label_version="label-v2"
        )
        if len(samples) < 40:
            return self._save(
                state="DATA_READY",
                reasons=["insufficient_labeled_samples"],
                dataset_version=frozen["dataset_version"],
            )
        quality = await ml_dataset.evaluate_data_quality(self.session_factory)
        current_21 = self._latest_model(MODEL_21_ID, ("SHADOW", "ACTIVE"))
        seconds_since_train = self._seconds_since(self.state.last_train_at)
        forward_drop = self._forward_drop("21_ORDER_FLOW_ML")
        retrain = ml_lifecycle.should_retrain(
            new_samples=max(0, quality.final_label_count - self.state.last_valid_label_count),
            seconds_since_last_train=seconds_since_train,
            performance_drop_bps=forward_drop,
            scheduled_interval_elapsed=(
                seconds_since_train >= ml_lifecycle.SCHEDULED_RETRAIN_SECONDS
            ),
        )
        if current_21 is not None and not retrain["retrain"]:
            return await self._evaluate_candidate_21(current_21, frozen, retrain)
        attempt_at = datetime.now(UTC).isoformat()
        self._save(
            state="TRAINING_MODEL_21",
            reasons=retrain["reasons"] or ["initial_training"],
            dataset_version=frozen["dataset_version"],
            last_attempt_at=attempt_at,
        )
        self.state.last_attempt_at = attempt_at
        result = ml_trainer.walk_forward_train(
            samples,
            self.base_dir,
            horizon=HORIZON,
            direction=DIRECTION,
            min_edge_bps=MIN_EDGE_BPS,
            code_sha=self.code_sha,
            dataset_version=frozen["dataset_version"],
            dataset_hash=frozen["dataset_hash"],
            feature_version=ml_trainer.FEATURE_VERSION_21,
            label_version="label-v2",
            training_cutoff_ts=frozen["training_cutoff_ts"],
        )
        if result.get("status") != "OK":
            return self._save(
                state="VALIDATION_FAILED",
                reasons=[result.get("status", "UNKNOWN")],
                dataset_version=frozen["dataset_version"],
            )
        post = ml_shadow.post_cost_validation(result["metrics"])
        model_state = "SHADOW" if post["passed"] else "VALIDATION_FAILED"
        self.registry.register(
            model_id=MODEL_21_ID,
            model_version=result["model_version"],
            artifact_path=result["artifact_path"],
            artifact_hash=result["artifact_hash"],
            dataset_version=frozen["dataset_version"],
            dataset_hash=frozen["dataset_hash"],
            feature_version=ml_trainer.FEATURE_VERSION_21,
            feature_schema_hash=result["feature_schema_hash"],
            label_version="label-v2",
            code_sha=self.code_sha,
            algorithm=ml_trainer.ALGORITHM_21,
            training_cutoff_ts=result["training_cutoff_ts"],
            training_window={"rows": len(samples)},
            validation_windows=result["metrics"]["folds"],
            hyperparameters={"n_folds": 3},
            metrics=result["metrics"],
            state=model_state,
        )
        if not post["passed"]:
            return self._save(
                state="VALIDATION_FAILED",
                reasons=post["reasons"],
                dataset_version=frozen["dataset_version"],
                model_21_version=result["model_version"],
            )
        loaded = self.artifact_resolver.resolve(MODEL_21_ID, result["model_version"])
        if loaded is None:
            return self._save(
                state="VALIDATION_FAILED",
                reasons=["artifact_integrity_failed"],
                dataset_version=frozen["dataset_version"],
                model_21_version=result["model_version"],
            )
        await self.forward.attach_natural_outcomes()
        predicted = await self.forward.generate(
            model_id=MODEL_21_ID,
            model_version=result["model_version"],
            artifact_hash=result["artifact_hash"],
            training_cutoff_ts=result["training_cutoff_ts"],
            loaded_artifact=loaded,
            feature_version=result["feature_version"],
            label_version="label-v2",
        )
        summary = await self.forward.summary(MODEL_21_ID, result["model_version"])
        decision = ml_shadow.decide_promotion(
            post_cost_passed=True,
            fold_count=result["fold_count"],
            shadow_summary=summary,
            min_shadow=ml_forward.TRUE_FORWARD_MIN_SAMPLES_21,
            artifact_integrity=True,
            schema_compatible=True,
        )
        if decision == "PROMOTE":
            self.registry.set_state(
                MODEL_21_ID, result["model_version"], "ACTIVE", reason="promotion_gate"
            )
        elif decision == "REJECT":
            self.registry.set_state(
                MODEL_21_ID, result["model_version"], "VALIDATION_FAILED", reason="promotion_reject"
            )
        model25 = None
        if ml_meta.can_train_25(self.registry):
            meta = ml_meta.train_meta_forecast(
                payload,
                self.base_dir,
                registry=self.registry,
                model21_artifact=loaded.metadata,
                model_21_version=loaded.model_version,
                model_21_artifact_hash=loaded.artifact_hash,
                model_21_artifact_status=loaded.registry_state,
                horizon=HORIZON,
                direction=DIRECTION,
                min_edge_bps=MIN_EDGE_BPS,
                code_sha=self.code_sha,
                dataset_version=frozen["dataset_version"],
                dataset_hash=frozen["dataset_hash"],
            )
            if meta.get("status") == "OK":
                model25 = meta["model_version"]
                loaded25 = self.artifact_resolver.resolve(ml_meta.MODEL_25_ID, model25)
                if loaded25 is not None:
                    from crypto_trader.ml_artifacts import LogisticPredictor

                    m21_predictor = LogisticPredictor(loaded.metadata)

                    def _m21_prob(snapshot_features, _predictor=m21_predictor):
                        try:
                            return float(_predictor(snapshot_features))
                        except Exception:
                            return None

                    def _build_meta_features(snapshot_features, _predictor=_m21_prob):
                        prob = _predictor(snapshot_features)
                        return ml_meta.meta_features(
                            {
                                "features": snapshot_features,
                                "market_regime": snapshot_features.get("market_regime"),
                            },
                            prob,
                        )

                    def _row_metadata(snapshot_features, _predictor=_m21_prob):
                        return {
                            "model21_probability": _predictor(snapshot_features),
                            "model21_version": loaded.model_version,
                            "model21_artifact_hash": loaded.artifact_hash,
                        }

                    await self.forward.generate(
                        model_id=ml_meta.MODEL_25_ID,
                        model_version=model25,
                        artifact_hash=meta["artifact_hash"],
                        training_cutoff_ts=meta["training_cutoff_ts"],
                        loaded_artifact=loaded25,
                        feature_builder=_build_meta_features,
                        row_metadata_builder=_row_metadata,
                        feature_version=meta["feature_version"],
                        label_version="label-v2",
                    )
                    summary25 = await self.forward.summary(ml_meta.MODEL_25_ID, model25)
                    decision25 = ml_shadow.decide_promotion(
                        post_cost_passed=True,
                        fold_count=meta["fold_count"],
                        shadow_summary=summary25,
                        min_shadow=ml_forward.TRUE_FORWARD_MIN_SAMPLES_25,
                        artifact_integrity=True,
                        schema_compatible=True,
                    )
                    if decision25 == "PROMOTE":
                        self.registry.set_state(
                            ml_meta.MODEL_25_ID,
                            model25,
                            "ACTIVE",
                            reason="promotion_gate_25",
                        )
                    elif decision25 == "REJECT":
                        self.registry.set_state(
                            ml_meta.MODEL_25_ID,
                            model25,
                            "VALIDATION_FAILED",
                            reason="promotion_reject_25",
                        )
                    summary25 = {**summary25, "decision": decision25}
                    self.state.model_25_forward = summary25
        if decision == "PROMOTE":
            state = "MODEL_21_ACTIVE"
        elif decision == "REJECT":
            state = "VALIDATION_FAILED"
        else:
            state = "SHADOW_MODEL_21"
        trained_at = datetime.now(UTC).isoformat()
        return self._save(
            state=state,
            reasons=[decision, f"forward_predicted={predicted}"],
            dataset_version=frozen["dataset_version"],
            model_21_version=result["model_version"],
            model_25_version=model25,
            model_21_forward=summary,
            retrain_reasons=retrain["reasons"],
            last_train_at=trained_at,
            last_valid_label_count=quality.final_label_count,
            last_dataset_version=frozen["dataset_version"],
        )
