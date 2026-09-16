# Immutable model registry for ML evidence models (LEARNING_ONLY).
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

MODEL_STATES = (
    "WAITING_FOR_DATA",
    "TRAINING",
    "VALIDATING",
    "VALIDATION_FAILED",
    "SHADOW",
    "ACTIVE",
    "DEGRADED",
    "REJECTED",
    "SUPERSEDED",
    "ROLLED_BACK",
)
TERMINAL_STATES = ("REJECTED", "SUPERSEDED", "ROLLED_BACK")


class ModelRegistry:
    """JSON-backed registry; model versions are immutable once registered."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.data = {"models": [], "active": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))

    def get(self, model_id: str, version: str) -> dict | None:
        for m in self.data["models"]:
            if m["model_id"] == model_id and m["model_version"] == version:
                return m
        return None

    def register(
        self,
        *,
        model_id: str,
        model_version: str,
        artifact_path: str,
        artifact_hash: str,
        dataset_version: str = "",
        dataset_hash: str = "",
        feature_version: str = "",
        feature_schema_hash: str = "",
        label_version: str = "",
        code_sha: str = "",
        algorithm: str = "",
        xgboost_version: str = "",
        training_cutoff_ts: str = "",
        seed: int | None = None,
        training_window: dict | None = None,
        validation_windows: list | None = None,
        hyperparameters: dict | None = None,
        metrics: dict | None = None,
        state: str = "VALIDATING",
    ) -> dict:
        if state not in MODEL_STATES:
            raise ValueError(f"invalid_state:{state}")
        existing = self.get(model_id, model_version)
        if existing is not None:
            return existing  # immutable: never overwrite a registered version
        entry = {
            "model_id": model_id,
            "model_version": model_version,
            "artifact_path": artifact_path,
            "artifact_hash": artifact_hash,
            "dataset_version": dataset_version,
            "dataset_hash": dataset_hash,
            "feature_version": feature_version,
            "feature_schema_hash": feature_schema_hash,
            "label_version": label_version,
            "code_sha": code_sha,
            "algorithm": algorithm,
            "xgboost_version": xgboost_version,
            "training_cutoff_ts": training_cutoff_ts,
            "seed": seed,
            "training_window": training_window or {},
            "validation_windows": validation_windows or [],
            "hyperparameters": hyperparameters or {},
            "metrics": metrics or {},
            "state": state,
            "created_at": datetime.now(UTC).isoformat(),
            "promoted_at": None,
            "superseded_at": None,
            "history": [],
        }
        self.data["models"].append(entry)
        self._save()
        return entry

    def set_state(
        self,
        model_id: str,
        version: str,
        state: str,
        *,
        reason: str = "",
        metrics: dict | None = None,
    ) -> dict:
        entry = self.get(model_id, version)
        if entry is None:
            raise KeyError(f"unknown_model:{model_id}:{version}")
        if state not in MODEL_STATES:
            raise ValueError(f"invalid_state:{state}")
        now = datetime.now(UTC).isoformat()
        entry["history"].append({"from": entry["state"], "to": state, "at": now, "reason": reason})
        entry["state"] = state
        if metrics:
            entry["metrics"].update(metrics)
        if state == "ACTIVE":
            previous = self.data["active"].get(model_id)
            if previous and previous.get("model_version") != version:
                prev = self.get(model_id, previous["model_version"])
                if prev is not None:
                    prev["state"] = "SUPERSEDED"
                    prev["superseded_at"] = now
            entry["promoted_at"] = now
            self.data["active"][model_id] = {"model_version": version, "promoted_at": now}
        if state in ("DEGRADED", "REJECTED", "ROLLED_BACK"):
            current = self.data["active"].get(model_id) or {}
            if current.get("model_version") == version:
                self.data["active"].pop(model_id, None)
        self._save()
        return entry

    def active_version(self, model_id: str) -> str | None:
        current = self.data["active"].get(model_id) or {}
        return current.get("model_version")

    def active_entry(self, model_id: str) -> dict | None:
        version = self.active_version(model_id)
        return self.get(model_id, version) if version else None
