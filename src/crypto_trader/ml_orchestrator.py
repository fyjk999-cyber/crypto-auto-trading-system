# ruff: noqa: B905, ASYNC240
# Autonomous ML trainer orchestration (deterministic, restart-safe).
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader import ml_artifacts, ml_dataset, ml_forward, ml_meta, ml_shadow, ml_trainer
from crypto_trader.ml_registry import ModelRegistry

MODEL_21_ID = "21_ORDER_FLOW_ML"
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
        self.state.last_error = last_error
        if state not in ("WAITING_FOR_DATA",):
            self.state.last_success = datetime.now(UTC).isoformat()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(self.state.__dict__)
        self.state_path.write_text(json.dumps(payload, indent=2, default=str))
        heartbeat = {
            "pid": __import__("os").getpid(),
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

    def _score(self, artifact: dict, sample: dict) -> float:
        vector = ml_trainer.vectorize(sample, artifact["preprocessing"])
        return ml_trainer.sigmoid(sum(w * v for w, v in zip(artifact["weights"], vector)))

    async def run_once(self) -> dict:
        readiness = await ml_dataset.evaluate_readiness(self.session_factory)
        if not readiness.ready:
            return self._save(state="WAITING_FOR_DATA", reasons=readiness.reasons)
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
        return self._save(
            state=state,
            reasons=[decision, f"forward_predicted={predicted}"],
            dataset_version=frozen["dataset_version"],
            model_21_version=result["model_version"],
            model_25_version=model25,
            model_21_forward=summary,
        )
