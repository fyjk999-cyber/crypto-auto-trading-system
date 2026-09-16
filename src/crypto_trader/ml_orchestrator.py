# ruff: noqa: B905, ASYNC240
# Autonomous ML trainer orchestration (deterministic, restart-safe).
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader import ml_dataset, ml_meta, ml_shadow, ml_trainer
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
        self.shadow = ml_shadow.ShadowStore(self.base_dir / "shadow" / "predictions.jsonl")
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
            self.session_factory, self.base_dir / "datasets", code_sha=self.code_sha
        )
        payload = json.loads(Path(frozen["path"]).read_text())
        samples = ml_trainer.build_samples(payload, HORIZON, DIRECTION, MIN_EDGE_BPS)
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
            feature_version="scan-features-v1",
            label_version="label-v1",
            code_sha=self.code_sha,
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
        artifact = json.loads(Path(result["artifact_path"]).read_text())
        for sample in samples[-50:]:
            probability = self._score(artifact, sample)
            self.shadow.record(
                model_id=MODEL_21_ID,
                model_version=result["model_version"],
                symbol="UNIVERSE",
                probability=probability,
                expected_edge=probability * result["metrics"]["walk_forward"]["mean_net_bps_valid"],
                confidence=abs(probability - 0.5) * 2.0,
            )
        summary = self.shadow.summary(MODEL_21_ID, result["model_version"])
        decision = ml_shadow.decide_promotion(
            post_cost_passed=True, fold_count=result["fold_count"], shadow_summary=summary
        )
        if decision == "PROMOTE":
            self.registry.set_state(
                MODEL_21_ID, result["model_version"], "ACTIVE", reason="promotion_gate"
            )
        model25 = None
        if ml_meta.can_train_25(self.registry):
            meta = ml_meta.train_meta_forecast(
                payload,
                self.base_dir,
                registry=self.registry,
                horizon=HORIZON,
                direction=DIRECTION,
                min_edge_bps=MIN_EDGE_BPS,
                code_sha=self.code_sha,
                dataset_version=frozen["dataset_version"],
            )
            if meta.get("status") == "OK":
                model25 = meta["model_version"]
        state = "MODEL_21_ACTIVE" if decision == "PROMOTE" else "SHADOW_MODEL_21"
        return self._save(
            state=state,
            reasons=[decision],
            dataset_version=frozen["dataset_version"],
            model_21_version=result["model_version"],
            model_25_version=model25,
        )
