# Autonomous retraining, degradation and rollback policy (LEARNING_ONLY).
from __future__ import annotations

from datetime import UTC, datetime

MIN_NEW_SAMPLES = 50
COOLDOWN_SECONDS = 6 * 3600
SCHEDULED_RETRAIN_SECONDS = 24 * 3600
MAX_DEGRADATION_BPS = 10.0
MIN_FORWARD_SAMPLES_FOR_DEGRADATION = 30

LIFECYCLE_STATES = (
    "WAITING_FOR_DATA",
    "DATA_ACCUMULATING",
    "DATA_READY",
    "TRAINING_MODEL_21",
    "VALIDATING_MODEL_21",
    "SHADOW_MODEL_21",
    "MODEL_21_PROMOTED",
    "MODEL_21_ACTIVE",
    "TRAINING_MODEL_25",
    "VALIDATING_MODEL_25",
    "SHADOW_MODEL_25",
    "MODEL_25_PROMOTED",
    "MODEL_25_ACTIVE",
    "ML_CLOSURE_PASS",
    "VALIDATION_FAILED",
    "DEGRADED",
    "ROLLED_BACK",
)


def should_retrain(
    *,
    new_samples: int,
    seconds_since_last_train: float,
    performance_drop_bps: float = 0.0,
    feature_version_changed: bool = False,
    label_version_changed: bool = False,
    regime_shift: bool = False,
    scheduled_interval_elapsed: bool = False,
    drift_detected: bool = False,
) -> dict:
    """Bounded deterministic retraining trigger; never a rapid retrain loop."""
    reasons = []
    bounded_new_data = int(new_samples) >= MIN_NEW_SAMPLES
    cooldown_ok = float(seconds_since_last_train) >= COOLDOWN_SECONDS
    if feature_version_changed:
        reasons.append("feature_version_changed")
    if label_version_changed:
        reasons.append("label_version_changed")
    if regime_shift:
        reasons.append("regime_shift")
    if drift_detected:
        reasons.append("feature_data_drift")
    if float(performance_drop_bps) >= MAX_DEGRADATION_BPS:
        reasons.append("performance_degradation")
    if scheduled_interval_elapsed and (bounded_new_data or reasons):
        reasons.append("scheduled_interval")
    if bounded_new_data and cooldown_ok:
        reasons.append("minimum_new_data_after_cooldown")
    if bounded_new_data and not cooldown_ok:
        reasons.append("cooldown_active")
    retrain = bool(reasons) and "cooldown_active" not in reasons
    return {"retrain": retrain, "reasons": reasons}


def assess_degradation(
    forward_summary: dict,
    *,
    baseline_mean_net_bps: float = 0.0,
    max_drop_bps: float = MAX_DEGRADATION_BPS,
    min_samples: int = MIN_FORWARD_SAMPLES_FOR_DEGRADATION,
) -> dict:
    """Versioned forward-performance degradation policy (natural evidence only)."""
    samples = int(forward_summary.get("samples", 0) or 0)
    mean_net = float(forward_summary.get("mean_net_bps", 0.0) or 0.0)
    if samples < min_samples:
        return {
            "degraded": False,
            "reason": "insufficient_true_forward_samples",
            "samples": samples,
            "mean_net_bps": mean_net,
        }
    drop = float(baseline_mean_net_bps) - mean_net
    return {
        "degraded": drop >= float(max_drop_bps),
        "reason": "forward_performance_degradation" if drop >= float(max_drop_bps) else "healthy",
        "samples": samples,
        "mean_net_bps": mean_net,
        "baseline_mean_net_bps": float(baseline_mean_net_bps),
        "drop_bps": drop,
    }


def mark_degraded(
    registry,
    model_id: str,
    version: str,
    *,
    reason: str,
    degradation_bps: float,
    metrics: dict | None = None,
) -> dict | None:
    if registry.active_version(model_id) != version:
        return None
    return registry.set_state(
        model_id,
        version,
        "DEGRADED",
        reason=f"{reason}:{degradation_bps:.2f}bps",
        metrics=metrics,
        details={
            "degradation_bps": degradation_bps,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def rollback(
    registry,
    model_id: str,
    *,
    reason: str = "rollback",
    metrics: dict | None = None,
    candidate_version: str | None = None,
) -> dict | None:
    """Restore the newest prior accepted artifact; never delete any artifact."""
    models = [m for m in registry.data["models"] if m["model_id"] == model_id]
    current = registry.active_version(model_id)
    degraded = [m for m in models if m["state"] == "DEGRADED"]
    old_version = current or (degraded[-1]["model_version"] if degraded else None)
    targets = [
        m
        for m in models
        if m["state"] in ("SUPERSEDED", "SHADOW")
        and m["model_version"] != candidate_version
    ]
    details = {
        "reason": reason,
        "old_version": old_version,
        "candidate_version": candidate_version,
        "result": None,
        "metrics": dict(metrics or {}),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if not targets:
        if old_version:
            registry.set_state(
                model_id,
                old_version,
                "ROLLED_BACK",
                reason=reason,
                metrics=metrics,
                details=details,
            )
        return None
    target = sorted(targets, key=lambda m: m["created_at"])[-1]
    details["result"] = target["model_version"]
    if old_version and old_version != target["model_version"]:
        registry.set_state(
            model_id,
            old_version,
            "ROLLED_BACK",
            reason=reason,
            metrics=metrics,
            details=details,
        )
    restored = registry.set_state(
        model_id,
        target["model_version"],
        "ACTIVE",
        reason=reason,
        metrics=metrics,
        details=details,
    )
    return restored
