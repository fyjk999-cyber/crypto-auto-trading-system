"""Prospective champion identity, canonical fingerprint and promotion gate."""

from __future__ import annotations

import json

import pytest

from crypto_trader.ml_registry import (
    FINGERPRINT_VERSION,
    FingerprintMismatchError,
    ModelRegistry,
    compute_model_fingerprint,
)


def _registry_with_candidate(tmp_path) -> tuple[ModelRegistry, dict]:
    registry = ModelRegistry(tmp_path / "registry.json")
    entry = registry.register(
        model_id="21_ORDER_FLOW_ML",
        model_version="v1",
        artifact_path="models/m21.pkl",
        artifact_hash="abc123",
        dataset_version="d1",
        dataset_hash="d1hash",
        feature_version="f2",
        feature_schema_hash="f2hash",
        label_version="label-v2",
        code_sha="c0ffee",
        algorithm="xgboost",
        xgboost_version="2.0.3",
        seed=7,
        metrics={"post_cost_expectancy_bps": 8.0},
    )
    return registry, entry


def test_new_candidate_persists_canonical_fingerprint(tmp_path):
    registry, entry = _registry_with_candidate(tmp_path)
    assert entry["fingerprint_version"] == FINGERPRINT_VERSION
    assert len(entry["fingerprint"]) == 64
    assert registry.verify_entry(entry) is True
    assert compute_model_fingerprint(entry) == entry["fingerprint"]

    reloaded = ModelRegistry(tmp_path / "registry.json")
    stored = reloaded.get("21_ORDER_FLOW_ML", "v1")
    assert stored is not None
    assert stored["fingerprint"] == entry["fingerprint"]


def test_tampered_artifact_fails_promotion_gate_closed(tmp_path):
    registry, entry = _registry_with_candidate(tmp_path)
    entry["artifact_hash"] = "tampered"
    assert registry.verify_entry(entry) is False
    with pytest.raises(FingerprintMismatchError):
        registry.promote("21_ORDER_FLOW_ML", "v1")
    assert registry.active_entry("21_ORDER_FLOW_ML") is None


def test_legacy_entry_gets_first_valid_fingerprint_only_on_promotion(tmp_path):
    registry, entry = _registry_with_candidate(tmp_path)
    entry.pop("fingerprint")
    entry.pop("fingerprint_version")
    registry._save()

    snapshot = registry.verify_active("21_ORDER_FLOW_ML")
    assert snapshot["fingerprint_match"] == "NOT_APPLICABLE_NO_HISTORICAL_CHAMPION"

    promoted = registry.promote("21_ORDER_FLOW_ML", "v1")
    assert promoted["state"] == "ACTIVE"
    assert registry.verify_entry(promoted) is True

    payload = json.loads((tmp_path / "registry.json").read_text())
    stored = next(
        item
        for item in payload["models"]
        if item["model_id"] == "21_ORDER_FLOW_ML" and item["model_version"] == "v1"
    )
    assert stored["fingerprint"] == compute_model_fingerprint(stored)


def test_expected_fingerprint_mismatch_is_rejected(tmp_path):
    registry, _entry = _registry_with_candidate(tmp_path)
    with pytest.raises(FingerprintMismatchError):
        registry.promote(
            "21_ORDER_FLOW_ML", "v1", expected_fingerprint="0" * 64
        )
    assert registry.active_entry("21_ORDER_FLOW_ML") is None
