# Canonical immutable ML artifact resolver / cache (LEARNING_ONLY).
"""Resolve registry ACTIVE artifacts, verify hashes, and expose predictors.

The registry and artifact hash are the source of truth. This module never
places, sizes or cancels an order; a loaded artifact can only emit evidence
probabilities for the expert layer.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crypto_trader import ml_trainer
from crypto_trader.ml_registry import ModelRegistry

MODEL_21_ID = "21_ORDER_FLOW_ML"
MODEL_25_ID = "25_META_FORECAST"
FINAL_LABEL_VERSION = "label-v2"
ACTIVE_ARTIFACT_STATUS = "ACTIVE_TRAINED_ARTIFACT"


class ArtifactIntegrityError(RuntimeError):
    """Registry ACTIVE entry points at a missing/corrupt/incompatible artifact."""


class ArtifactNotActiveError(RuntimeError):
    """A caller required an ACTIVE artifact but none was active."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


@dataclass(frozen=True)
class LoadedArtifact:
    """Verified immutable artifact plus its inference callable."""

    model_id: str
    model_version: str
    artifact_hash: str
    artifact_path: str
    metadata: dict[str, Any]
    predictor: Callable[[dict[str, Any]], float]
    registry_state: str
    artifact_status: str = ACTIVE_ARTIFACT_STATUS

    @property
    def dataset_version(self) -> str:
        return str(self.metadata.get("dataset_version") or "")

    @property
    def dataset_hash(self) -> str:
        return str(self.metadata.get("dataset_hash") or "")

    @property
    def feature_version(self) -> str:
        return str(self.metadata.get("feature_version") or "")

    @property
    def feature_schema_hash(self) -> str:
        return str(self.metadata.get("feature_schema_hash") or "")

    @property
    def label_version(self) -> str:
        return str(self.metadata.get("label_version") or "")

    @property
    def training_cutoff_ts(self) -> str:
        return str(self.metadata.get("training_cutoff_ts") or "")

    @property
    def algorithm(self) -> str:
        return str(self.metadata.get("algorithm") or "")

    @property
    def xgboost_version(self) -> str:
        return str(self.metadata.get("xgboost_version") or "")

    def predict(self, features: dict[str, Any]) -> float:
        probability = float(self.predictor(features))
        if math.isnan(probability) or math.isinf(probability):
            raise ArtifactIntegrityError("NON_FINITE_PREDICTION")
        return min(1.0, max(0.0, probability))


class LogisticPredictor:
    """#21 deterministic calibrated/logistic artifact predictor."""

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.features = list(metadata.get("features") or [])
        self.preprocessing = metadata.get("preprocessing") or {}
        self.weights = list(metadata.get("weights") or [])
        if not self.features or len(self.weights) != len(self.features) + 1:
            raise ArtifactIntegrityError("INVALID_LOGISTIC_ARTIFACT")

    def __call__(self, snapshot_features: dict[str, Any]) -> float:
        base = ml_trainer.extract_features(snapshot_features)
        medians = self.preprocessing.get("medians") or {}
        means = self.preprocessing.get("means") or []
        stds = self.preprocessing.get("stds") or []
        vector = [1.0]
        for idx, name in enumerate(self.features):
            value = base.get(name)
            if value is None:
                value = medians.get(name, 0.0)
            mean = means[idx] if idx < len(means) else 0.0
            std = stds[idx] if idx < len(stds) and stds[idx] else 1.0
            vector.append((float(value) - float(mean)) / float(std))
        return ml_trainer.sigmoid(sum(w * v for w, v in zip(self.weights, vector, strict=False)))


class XGBoostPredictor:
    """#25 literal XGBoost predictor loaded from the artifact model file."""

    def __init__(self, metadata: dict[str, Any]) -> None:
        import xgboost as xgb

        model_path = metadata.get("xgboost_model_path")
        expected_hash = metadata.get("xgboost_model_hash")
        if not model_path or not expected_hash:
            raise ArtifactIntegrityError("MISSING_XGBOOST_MODEL_FILE")
        path = Path(model_path)
        if not path.exists():
            raise ArtifactIntegrityError("MISSING_XGBOOST_MODEL_FILE")
        if sha256_file(path) != expected_hash:
            raise ArtifactIntegrityError("XGBOOST_MODEL_HASH_MISMATCH")
        self.model = xgb.Booster()
        self.model.load_model(str(path))
        self.features = list(metadata.get("features") or [])
        if not self.features:
            raise ArtifactIntegrityError("MISSING_XGBOOST_FEATURES")
        self.xgboost_version = str(metadata.get("xgboost_version") or xgb.__version__)

    def __call__(self, meta_features: dict[str, Any]) -> float:
        import xgboost as xgb

        row = [float(meta_features.get(name) or 0.0) for name in self.features]
        matrix = xgb.DMatrix([row], feature_names=self.features)
        return float(self.model.predict(matrix)[0])


class ArtifactResolver:
    """Bounded cache keyed by (model_id, model_version, artifact_hash)."""

    def __init__(self, registry: ModelRegistry, *, max_cache_size: int = 8) -> None:
        self.registry = registry
        self.max_cache_size = max(1, int(max_cache_size))
        self._cache: dict[tuple[str, str, str], LoadedArtifact] = {}
        self.last_error: str | None = None

    def clear(self) -> None:
        self._cache.clear()

    def _entry(self, model_id: str, version: str | None, *, require_active: bool) -> dict | None:
        if require_active:
            entry = self.registry.active_entry(model_id)
            if entry is None:
                raise ArtifactNotActiveError(f"NO_ACTIVE_ARTIFACT:{model_id}")
            if self.registry.active_version(model_id) != entry.get("model_version"):
                raise ArtifactIntegrityError(f"REGISTRY_ACTIVE_MISMATCH:{model_id}")
            return entry
        if version is None:
            return self.registry.active_entry(model_id)
        return self.registry.get(model_id, version)

    def resolve(
        self,
        model_id: str,
        version: str | None = None,
        *,
        require_active: bool = False,
    ) -> LoadedArtifact | None:
        try:
            entry = self._entry(model_id, version, require_active=require_active)
        except (ArtifactNotActiveError, ArtifactIntegrityError) as exc:
            self.last_error = str(exc)
            raise
        if entry is None:
            self.last_error = f"UNKNOWN_ARTIFACT:{model_id}:{version}"
            return None
        model_version = str(entry.get("model_version") or "")
        artifact_hash = str(entry.get("artifact_hash") or "")
        cache_key = (model_id, model_version, artifact_hash)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            loaded = self._load_entry(entry, require_active=require_active)
        except ArtifactIntegrityError as exc:
            self.last_error = str(exc)
            raise
        self._cache[cache_key] = loaded
        if len(self._cache) > self.max_cache_size:
            self._cache.pop(next(iter(self._cache)))
        return loaded

    def resolve_active(self, model_id: str) -> LoadedArtifact | None:
        try:
            return self.resolve(model_id, require_active=True)
        except ArtifactNotActiveError:
            return None

    def _load_entry(self, entry: dict, *, require_active: bool) -> LoadedArtifact:
        model_id = str(entry.get("model_id") or "")
        model_version = str(entry.get("model_version") or "")
        artifact_hash = str(entry.get("artifact_hash") or "")
        artifact_path = str(entry.get("artifact_path") or "")
        if not model_id or not model_version or not artifact_hash or not artifact_path:
            raise ArtifactIntegrityError("INCOMPLETE_REGISTRY_ENTRY")
        if require_active and entry.get("state") != "ACTIVE":
            raise ArtifactIntegrityError(f"REGISTRY_NOT_ACTIVE:{model_id}:{model_version}")
        path = Path(artifact_path)
        if not path.exists():
            raise ArtifactIntegrityError(f"MISSING_ARTIFACT:{model_id}:{model_version}")
        actual_hash = sha256_file(path)
        if actual_hash != artifact_hash:
            raise ArtifactIntegrityError(f"ARTIFACT_HASH_MISMATCH:{model_id}:{model_version}")
        try:
            metadata = json.loads(path.read_text())
        except Exception as exc:
            raise ArtifactIntegrityError(f"CORRUPT_ARTIFACT_JSON:{model_id}") from exc
        if str(metadata.get("model_id") or "") != model_id:
            raise ArtifactIntegrityError("ARTIFACT_MODEL_ID_MISMATCH")
        if str(metadata.get("model_version") or "") not in ("", model_version):
            raise ArtifactIntegrityError("ARTIFACT_MODEL_VERSION_MISMATCH")
        metadata.setdefault("model_version", model_version)
        if str(metadata.get("label_version") or "") != FINAL_LABEL_VERSION:
            raise ArtifactIntegrityError("ARTIFACT_LABEL_VERSION_NOT_LABEL_V2")
        entry_schema = str(entry.get("feature_schema_hash") or "")
        metadata_schema = str(metadata.get("feature_schema_hash") or "")
        if entry_schema and metadata_schema and entry_schema != metadata_schema:
            raise ArtifactIntegrityError("FEATURE_SCHEMA_HASH_MISMATCH")
        if model_id == MODEL_21_ID:
            predictor = LogisticPredictor(metadata)
        elif model_id == MODEL_25_ID:
            predictor = XGBoostPredictor(metadata)
        else:
            raise ArtifactIntegrityError(f"UNSUPPORTED_MODEL_ID:{model_id}")
        return LoadedArtifact(
            model_id=model_id,
            model_version=model_version,
            artifact_hash=artifact_hash,
            artifact_path=artifact_path,
            metadata=metadata,
            predictor=predictor,
            registry_state=str(entry.get("state") or ""),
        )
