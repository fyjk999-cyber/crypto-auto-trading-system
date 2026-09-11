"""G13: card quality and decay.

Reuses the existing ``MemoryGovernor`` quality formula and
``KnowledgeDecayEngine``; this module only supplies card-specific axes,
versioned thresholds and the small CANDIDATE/ACTIVE/WATCH/STALE/RETIRED status
mapping.  Confidence is never ``wins / samples``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.intelligence.knowledge.decay import KnowledgeDecayEngine, KnowledgeHealth
from crypto_trader.learning.growth_v2_contracts import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_RETIRED,
    STATUS_STALE,
    STATUS_WATCH,
)
from crypto_trader.memory_governance.governor import MemoryGovernor


@dataclass(frozen=True)
class CardQualityPolicy:
    version: str = "card-quality-v1"
    min_samples_for_active: int = 3
    min_repeatability: float = 0.5
    min_evidence_quality: float = 0.6
    max_contradiction_rate_for_active: float = 0.25
    contradiction_penalty_weight: float = 0.4
    stale_after_days: float = 90.0
    retire_on_invalid: bool = False
    require_complete_trigger: bool = True
    require_known_regime: bool = True

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "min_samples_for_active": self.min_samples_for_active,
            "min_repeatability": self.min_repeatability,
            "min_evidence_quality": self.min_evidence_quality,
            "max_contradiction_rate_for_active": (
                self.max_contradiction_rate_for_active
            ),
            "contradiction_penalty_weight": self.contradiction_penalty_weight,
            "stale_after_days": self.stale_after_days,
            "retire_on_invalid": self.retire_on_invalid,
            "require_complete_trigger": self.require_complete_trigger,
            "require_known_regime": self.require_known_regime,
        }


@dataclass
class CardQualityAssessment:
    quality_score: Decimal
    confidence_level: str
    status: str
    health: KnowledgeHealth
    axes: dict[str, float] = field(default_factory=dict)
    promotion_ready: bool = False
    reasons: list[str] = field(default_factory=list)
    policy_version: str = "card-quality-v1"
    performance_change_status: str = "UNKNOWN"


def _rate(support: int, contradiction: int) -> float:
    total = support + contradiction
    return (contradiction / total) if total else 0.0


def assess_card_quality(
    *,
    knowledge_id: str,
    sample_count: int,
    support_count: int,
    contradiction_count: int,
    trigger_complete: bool,
    regime_known: bool,
    evidence_quality: float,
    regime_consistency: float,
    repeatability: float,
    confidence_input: float,
    now: datetime,
    last_validated_at: datetime | None = None,
    policy: CardQualityPolicy | None = None,
) -> CardQualityAssessment:
    policy = policy or CardQualityPolicy()
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    reference = last_validated_at or now
    reference = (
        reference.replace(tzinfo=UTC)
        if reference.tzinfo is None
        else reference.astimezone(UTC)
    )
    age_days = max(0.0, (now - reference).total_seconds() / 86400.0)
    contradiction_rate = _rate(support_count, contradiction_count)

    governor = MemoryGovernor()
    base = governor.score(
        sample_size=max(0, sample_count),
        repeatability=max(0.0, min(1.0, repeatability)),
        regime_match=max(0.0, min(1.0, regime_consistency)),
        confidence=max(0.0, min(1.0, confidence_input)),
        # ``outcome_quality`` must not be a win rate; the caller supplies an
        # evidence-completeness score instead, and unknown evidence is 0.
        outcome_quality=max(0.0, min(1.0, evidence_quality)),
    ).score
    penalized = max(
        0.0,
        base * (1.0 - policy.contradiction_penalty_weight * contradiction_rate),
    )

    health = KnowledgeDecayEngine().evaluate(
        knowledge_id=knowledge_id,
        age_days=age_days,
        # Performance change is not fabricated: the engine receives neutral 0
        # and the caller can see that the value is UNKNOWN.
        performance_change=0.0,
        regime_change=max(0.0, 1.0 - max(0.0, min(1.0, regime_consistency))),
        contradiction_frequency=contradiction_rate,
    )

    reasons: list[str] = []
    if sample_count < policy.min_samples_for_active:
        reasons.append("INSUFFICIENT_SAMPLES")
    if policy.require_complete_trigger and not trigger_complete:
        reasons.append("TRIGGER_INCOMPLETE")
    if policy.require_known_regime and not regime_known:
        reasons.append("REGIME_UNKNOWN")
    if repeatability < policy.min_repeatability:
        reasons.append("LOW_REPEATABILITY")
    if evidence_quality < policy.min_evidence_quality:
        reasons.append("LOW_EVIDENCE_QUALITY")
    if contradiction_rate > policy.max_contradiction_rate_for_active:
        reasons.append("CONTRADICTION_RATE_HIGH")
    promotion_ready = not reasons

    if health.status in {"INVALID", "DEGRADED"}:
        status = STATUS_RETIRED if (policy.retire_on_invalid and health.status == "INVALID") else (
            STATUS_STALE if health.status == "INVALID" else STATUS_WATCH
        )
    elif reasons and reasons != ["INSUFFICIENT_SAMPLES"]:
        status = STATUS_WATCH if sample_count >= policy.min_samples_for_active else STATUS_CANDIDATE
    elif promotion_ready:
        status = STATUS_ACTIVE
    else:
        status = STATUS_CANDIDATE

    if not promotion_ready and status == STATUS_ACTIVE:
        status = STATUS_CANDIDATE

    if not trigger_complete or not regime_known or sample_count < policy.min_samples_for_active:
        confidence_level = "INSUFFICIENT_DATA"
    elif contradiction_rate > policy.max_contradiction_rate_for_active:
        confidence_level = "LOW_CONFIDENCE"
    elif penalized >= 0.7:
        confidence_level = "HIGH"
    elif penalized >= 0.45:
        confidence_level = "MEDIUM"
    else:
        confidence_level = "LOW_CONFIDENCE"

    axes = {
        "sample_coverage": min(1.0, sample_count / max(1, policy.min_samples_for_active * 4)),
        "evidence_quality": max(0.0, min(1.0, evidence_quality)),
        "contradiction_rate": round(contradiction_rate, 4),
        "regime_consistency": max(0.0, min(1.0, regime_consistency)),
        "repeatability": max(0.0, min(1.0, repeatability)),
        "recency_days": round(age_days, 4),
        "base_governor_score": base,
    }
    return CardQualityAssessment(
        quality_score=Decimal(str(round(penalized, 6))),
        confidence_level=confidence_level,
        status=status,
        health=health,
        axes=axes,
        promotion_ready=promotion_ready,
        reasons=reasons,
        policy_version=policy.version,
        performance_change_status="UNKNOWN",
    )
