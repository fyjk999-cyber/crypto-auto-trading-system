# Autonomous retraining, degradation and rollback policy (LEARNING_ONLY).
from __future__ import annotations

MIN_NEW_SAMPLES = 50
COOLDOWN_SECONDS = 6 * 3600
MAX_DEGRADATION_BPS = 10.0


def should_retrain(
    *,
    new_samples: int,
    seconds_since_last_train: float,
    performance_drop_bps: float = 0.0,
    feature_version_changed: bool = False,
    label_version_changed: bool = False,
    regime_shift: bool = False,
) -> dict:
    reasons = []
    if feature_version_changed:
        reasons.append("feature_version_changed")
    if label_version_changed:
        reasons.append("label_version_changed")
    if regime_shift:
        reasons.append("regime_shift")
    if performance_drop_bps >= MAX_DEGRADATION_BPS:
        reasons.append("performance_degradation")
    if new_samples >= MIN_NEW_SAMPLES and seconds_since_last_train >= COOLDOWN_SECONDS:
        reasons.append("minimum_new_data_after_cooldown")
    if new_samples >= MIN_NEW_SAMPLES and not reasons:
        reasons.append("cooldown_active")
    return {"retrain": bool(reasons) and "cooldown_active" not in reasons, "reasons": reasons}


def mark_degraded(
    registry, model_id: str, version: str, *, reason: str, degradation_bps: float
) -> dict | None:
    if registry.active_version(model_id) != version:
        return None
    return registry.set_state(
        model_id, version, "DEGRADED", reason=f"{reason}:{degradation_bps:.2f}bps"
    )


def rollback(registry, model_id: str, *, reason: str = "rollback") -> dict | None:
    models = [m for m in registry.data["models"] if m["model_id"] == model_id]
    current = registry.active_version(model_id)
    if not current:
        degraded = [m for m in models if m["state"] == "DEGRADED"]
        current = degraded[-1]["model_version"] if degraded else None
    targets = [m for m in models if m["state"] in ("SUPERSEDED", "SHADOW")]
    if not targets:
        if current:
            registry.set_state(model_id, current, "ROLLED_BACK", reason=reason)
        return None
    target = sorted(targets, key=lambda m: m["created_at"])[-1]
    if current and current != target["model_version"]:
        registry.set_state(model_id, current, "ROLLED_BACK", reason=reason)
    return registry.set_state(model_id, target["model_version"], "ACTIVE", reason=reason)
