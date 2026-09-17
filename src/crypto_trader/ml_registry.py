# Immutable model registry for ML evidence models (LEARNING_ONLY).
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

FINGERPRINT_VERSION = "sha256_canonical_json_v1"
FINGERPRINT_FIELDS = (
    "model_id",
    "model_version",
    "artifact_path",
    "artifact_hash",
    "dataset_version",
    "dataset_hash",
    "feature_version",
    "feature_schema_hash",
    "label_version",
    "code_sha",
    "algorithm",
    "xgboost_version",
    "seed",
    "training_cutoff_ts",
    "training_window",
    "validation_windows",
    "hyperparameters",
)

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


class FingerprintMismatchError(ValueError):
    """Raised when persisted champion fingerprint does not match canonical inputs."""


def canonical_fingerprint_payload(entry: dict) -> dict:
    return {field: entry.get(field) for field in FINGERPRINT_FIELDS}


def compute_model_fingerprint(entry: dict) -> str:
    """Independent, deterministic fingerprint over promoted model identity."""
    canonical = json.dumps(
        canonical_fingerprint_payload(entry),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic durable persistence: fsync temp file then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class ModelRegistry:
    """JSON-backed registry; model versions are immutable once registered."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.data = {"models": [], "active": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def _save(self) -> None:
        _atomic_write_json(self.path, self.data)

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
        entry["fingerprint"] = compute_model_fingerprint(entry)
        entry["fingerprint_version"] = FINGERPRINT_VERSION
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
        details: dict | None = None,
    ) -> dict:
        entry = self.get(model_id, version)
        if entry is None:
            raise KeyError(f"unknown_model:{model_id}:{version}")
        if state not in MODEL_STATES:
            raise ValueError(f"invalid_state:{state}")
        if state == "ACTIVE":
            self._prepare_promotion(entry)
        now = datetime.now(UTC).isoformat()
        entry["history"].append(
            {
                "from": entry["state"],
                "to": state,
                "at": now,
                "reason": reason,
                "details": dict(details or {}),
            }
        )
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

    def _prepare_promotion(
        self, entry: dict, expected_fingerprint: str | None = None
    ) -> str:
        """Fail closed unless canonical fingerprint matches persisted evidence.

        Historical entries without a fingerprint get the first prospective
        fingerprint at promotion; they are never fabricated from runtime state.
        """
        computed = compute_model_fingerprint(entry)
        stored = entry.get("fingerprint")
        if stored:
            if stored != computed:
                raise FingerprintMismatchError(
                    f"fingerprint_mismatch:{entry.get('model_id')}:{entry.get('model_version')}"
                )
            if expected_fingerprint and expected_fingerprint != computed:
                raise FingerprintMismatchError("expected_fingerprint_mismatch")
            return computed
        entry["fingerprint"] = computed
        entry["fingerprint_version"] = FINGERPRINT_VERSION
        if expected_fingerprint and expected_fingerprint != computed:
            raise FingerprintMismatchError("expected_fingerprint_mismatch")
        return computed

    def verify_entry(self, entry: dict) -> bool:
        stored = entry.get("fingerprint")
        return bool(stored) and stored == compute_model_fingerprint(entry)

    def verify_active(self, model_id: str) -> dict:
        entry = self.active_entry(model_id)
        if entry is None:
            return {
                "model_id": model_id,
                "champion_id": None,
                "stored_fingerprint": None,
                "recomputed_fingerprint": None,
                "fingerprint_match": "NOT_APPLICABLE_NO_HISTORICAL_CHAMPION",
                "fingerprint_version": FINGERPRINT_VERSION,
            }
        recomputed = compute_model_fingerprint(entry)
        return {
            "model_id": model_id,
            "champion_id": f"{model_id}:{entry['model_version']}",
            "stored_fingerprint": entry.get("fingerprint"),
            "recomputed_fingerprint": recomputed,
            "fingerprint_match": entry.get("fingerprint") == recomputed,
            "fingerprint_version": entry.get("fingerprint_version", FINGERPRINT_VERSION),
        }

    def promote(
        self,
        model_id: str,
        version: str,
        *,
        reason: str = "deterministic_promotion",
        expected_fingerprint: str | None = None,
    ) -> dict:
        """Atomic promotion gate; tampered/changed evidence is rejected."""
        entry = self.get(model_id, version)
        if entry is None:
            raise KeyError(f"unknown_model:{model_id}:{version}")
        self._prepare_promotion(entry, expected_fingerprint=expected_fingerprint)
        self._save()
        return self.set_state(model_id, version, "ACTIVE", reason=reason)

    def active_version(self, model_id: str) -> str | None:
        current = self.data["active"].get(model_id) or {}
        return current.get("model_version")

    def active_entry(self, model_id: str) -> dict | None:
        version = self.active_version(model_id)
        return self.get(model_id, version) if version else None
