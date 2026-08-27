"""Daily Learning Brain bridge: evidence package + factor attribution V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class DailyExperiencePackage:
    package_id: str
    period_id: str
    decision_ids: tuple[str, ...]
    factor_snapshot_ids: tuple[str, ...]
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "package_id": self.package_id,
            "period_id": self.period_id,
            "decision_ids": list(self.decision_ids),
            "factor_snapshot_ids": list(self.factor_snapshot_ids),
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class FactorAttributionResult:
    attribution_id: str
    review_id: str
    decision_id: str
    factor_snapshot_id: str
    factor_set_version: str
    supporting_factors: tuple[str, ...]
    opposing_factors: tuple[str, ...]
    dominant_factors: tuple[str, ...]
    conflicts: tuple[str, ...]
    health_issues: tuple[str, ...]
    factor_contributions: dict[str, str]
    decision_quality: str
    outcome_quality: str
    failure_candidates: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    confidence: str
    candidate_lessons: tuple[str, ...]


def build_attribution_v1(
    *,
    attribution_id: str,
    review_id: str,
    evidence: dict,
    decision_quality: str,
    outcome_quality: str,
) -> FactorAttributionResult:
    factors = evidence.get("factors", {})
    supporting = tuple(factors.keys())
    return FactorAttributionResult(
        attribution_id=attribution_id,
        review_id=review_id,
        decision_id=evidence.get("decision_id", ""),
        factor_snapshot_id=evidence.get("factor_snapshot_id", ""),
        factor_set_version=evidence.get("factor_set_version", ""),
        supporting_factors=supporting,
        opposing_factors=(),
        dominant_factors=(),
        conflicts=(),
        health_issues=(),
        factor_contributions={},
        decision_quality=decision_quality,
        outcome_quality=outcome_quality,
        failure_candidates=(),
        evidence_refs=(evidence.get("factor_snapshot_id", ""),),
        confidence="0.5",
        candidate_lessons=(),
    )
