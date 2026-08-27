"""Weekly/Monthly/Yearly review result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class WeeklyReviewResult:
    review_id: str
    period_id: str
    starts_at: str
    ends_at: str
    daily_review_ids: list
    trade_count: int = 0
    decision_count: int = 0
    weekly_pnl: str = "0"
    weekly_drawdown: str = "0"
    decision_quality_summary: dict = field(default_factory=dict)
    error_cluster_summary: list = field(default_factory=list)
    factor_quality_summary: dict = field(default_factory=dict)
    strategy_quality_summary: dict = field(default_factory=dict)
    regime_summary: dict = field(default_factory=dict)
    confirmed_lessons: list = field(default_factory=list)
    invalidated_lessons: list = field(default_factory=list)
    candidate_lessons: list = field(default_factory=list)
    persistent_patterns: list = field(default_factory=list)
    new_patterns: list = field(default_factory=list)
    disappearing_patterns: list = field(default_factory=list)
    research_questions: list = field(default_factory=list)
    data_quality: str = "OK"
    warnings: list = field(default_factory=list)
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "period_id": self.period_id,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "daily_review_ids": list(self.daily_review_ids),
            "trade_count": self.trade_count,
            "decision_count": self.decision_count,
            "weekly_pnl": self.weekly_pnl,
            "weekly_drawdown": self.weekly_drawdown,
            "decision_quality_summary": dict(self.decision_quality_summary),
            "error_cluster_summary": list(self.error_cluster_summary),
            "factor_quality_summary": dict(self.factor_quality_summary),
            "strategy_quality_summary": dict(self.strategy_quality_summary),
            "regime_summary": dict(self.regime_summary),
            "confirmed_lessons": list(self.confirmed_lessons),
            "invalidated_lessons": list(self.invalidated_lessons),
            "candidate_lessons": list(self.candidate_lessons),
            "persistent_patterns": list(self.persistent_patterns),
            "new_patterns": list(self.new_patterns),
            "disappearing_patterns": list(self.disappearing_patterns),
            "research_questions": list(self.research_questions),
            "data_quality": self.data_quality,
            "warnings": list(self.warnings),
            "created_at_utc": self.created_at_utc,
        }


@dataclass
class MonthlyReviewResult:
    review_id: str
    period_id: str
    starts_at: str
    ends_at: str
    weekly_review_ids: list
    strategy_evaluations: list = field(default_factory=list)
    factor_evaluations: list = field(default_factory=list)
    regime_matrix: dict = field(default_factory=dict)
    risk_summary: dict = field(default_factory=dict)
    execution_summary: dict = field(default_factory=dict)
    confirmed_lessons: list = field(default_factory=list)
    invalidated_lessons: list = field(default_factory=list)
    research_questions: list = field(default_factory=list)
    strategy_proposals: list = field(default_factory=list)
    factor_proposals: list = field(default_factory=list)
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "period_id": self.period_id,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "weekly_review_ids": list(self.weekly_review_ids),
            "strategy_evaluations": list(self.strategy_evaluations),
            "factor_evaluations": list(self.factor_evaluations),
            "regime_matrix": dict(self.regime_matrix),
            "risk_summary": dict(self.risk_summary),
            "execution_summary": dict(self.execution_summary),
            "confirmed_lessons": list(self.confirmed_lessons),
            "invalidated_lessons": list(self.invalidated_lessons),
            "research_questions": list(self.research_questions),
            "strategy_proposals": list(self.strategy_proposals),
            "factor_proposals": list(self.factor_proposals),
            "created_at_utc": self.created_at_utc,
        }


@dataclass
class YearlyReviewResult:
    review_id: str
    period_id: str
    starts_at: str
    ends_at: str
    monthly_review_ids: list
    annual_return: str = "0"
    max_drawdown: str = "0"
    tail_risk: str = "0"
    strategy_lifespan: list = field(default_factory=list)
    factor_lifespan: list = field(default_factory=list)
    version_lineage: list = field(default_factory=list)
    complexity_growth: list = field(default_factory=list)
    lesson_effectiveness: list = field(default_factory=list)
    architecture_proposals: list = field(default_factory=list)
    research_policy_proposals: list = field(default_factory=list)
    complexity_reduction_proposals: list = field(default_factory=list)
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "period_id": self.period_id,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "monthly_review_ids": list(self.monthly_review_ids),
            "annual_return": self.annual_return,
            "max_drawdown": self.max_drawdown,
            "tail_risk": self.tail_risk,
            "strategy_lifespan": list(self.strategy_lifespan),
            "factor_lifespan": list(self.factor_lifespan),
            "version_lineage": list(self.version_lineage),
            "complexity_growth": list(self.complexity_growth),
            "lesson_effectiveness": list(self.lesson_effectiveness),
            "architecture_proposals": list(self.architecture_proposals),
            "research_policy_proposals": list(self.research_policy_proposals),
            "complexity_reduction_proposals": list(self.complexity_reduction_proposals),
            "created_at_utc": self.created_at_utc,
        }
