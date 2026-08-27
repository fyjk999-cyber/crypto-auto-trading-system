"""Daily review contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class DailyReviewResult:
    review_id: str
    review_type: str = "DAILY"
    period_id: str = ""
    starts_at: str = ""
    ends_at: str = ""
    triggered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    decision_count: int = 0
    trade_count: int = 0
    gross_pnl: str = "0"
    net_pnl: str = "0"
    fees: str = "0"
    funding: str = "0"
    win_rate: str = "0"
    profit_factor: str = "0"
    expectancy: str = "0"
    average_r: str = "0"
    reviewed_decisions: list = field(default_factory=list)
    factor_attributions: list = field(default_factory=list)
    error_clusters: list = field(default_factory=list)
    patterns: list = field(default_factory=list)
    candidate_lessons: list = field(default_factory=list)
    data_quality: str = "OK"
    warnings: list = field(default_factory=list)
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "COMPLETED"

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "review_type": self.review_type,
            "period_id": self.period_id,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "triggered_at": self.triggered_at,
            "decision_count": self.decision_count,
            "trade_count": self.trade_count,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "fees": self.fees,
            "funding": self.funding,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "average_r": self.average_r,
            "reviewed_decisions": list(self.reviewed_decisions),
            "factor_attributions": list(self.factor_attributions),
            "error_clusters": list(self.error_clusters),
            "patterns": list(self.patterns),
            "candidate_lessons": list(self.candidate_lessons),
            "data_quality": self.data_quality,
            "warnings": list(self.warnings),
            "created_at_utc": self.created_at_utc,
            "status": self.status,
        }


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
