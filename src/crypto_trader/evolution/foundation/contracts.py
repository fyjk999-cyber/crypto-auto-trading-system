"""Evolution Brain contracts. Specifications only, no production activation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class EvolutionIntake:
    intake_id: str
    source_type: str
    source_ids: tuple[str, ...]
    lesson_ids: tuple[str, ...]
    pattern_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    scope: str
    problem_statement: str
    evidence_count: int
    independent_period_count: int
    contradiction_count: int
    confidence: float
    status: str = "NEW"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "intake_id": self.intake_id,
            "source_type": self.source_type,
            "source_ids": list(self.source_ids),
            "lesson_ids": list(self.lesson_ids),
            "pattern_ids": list(self.pattern_ids),
            "review_ids": list(self.review_ids),
            "scope": self.scope,
            "problem_statement": self.problem_statement,
            "evidence_count": self.evidence_count,
            "independent_period_count": self.independent_period_count,
            "contradiction_count": self.contradiction_count,
            "confidence": self.confidence,
            "status": self.status,
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class ResearchReport:
    research_id: str
    intake_id: str
    question: str
    scope: str
    internal_evidence_refs: tuple[str, ...]
    external_evidence_refs: tuple[str, ...]
    mechanisms_considered: tuple[str, ...]
    supporting_findings: tuple[str, ...]
    contradicting_findings: tuple[str, ...]
    known_unknowns: tuple[str, ...]
    confidence: float
    recommendation: str
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "research_id": self.research_id,
            "intake_id": self.intake_id,
            "question": self.question,
            "scope": self.scope,
            "internal_evidence_refs": list(self.internal_evidence_refs),
            "external_evidence_refs": list(self.external_evidence_refs),
            "mechanisms_considered": list(self.mechanisms_considered),
            "supporting_findings": list(self.supporting_findings),
            "contradicting_findings": list(self.contradicting_findings),
            "known_unknowns": list(self.known_unknowns),
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class EvolutionHypothesis:
    hypothesis_id: str
    source_intake_id: str
    source_lesson_ids: tuple[str, ...]
    source_pattern_ids: tuple[str, ...]
    source_research_ids: tuple[str, ...]
    scope: str
    target_type: str
    target_id: str
    problem_statement: str
    mechanism: str
    proposed_change: str
    expected_benefit: str
    possible_harm: str
    predicted_metric_changes: dict
    success_metrics: tuple[str, ...]
    guardrail_metrics: tuple[str, ...]
    test_plan: tuple[str, ...]
    confidence: float
    status: str = "PROPOSED"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "source_intake_id": self.source_intake_id,
            "source_lesson_ids": list(self.source_lesson_ids),
            "source_pattern_ids": list(self.source_pattern_ids),
            "source_research_ids": list(self.source_research_ids),
            "scope": self.scope,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "problem_statement": self.problem_statement,
            "mechanism": self.mechanism,
            "proposed_change": self.proposed_change,
            "expected_benefit": self.expected_benefit,
            "possible_harm": self.possible_harm,
            "predicted_metric_changes": dict(self.predicted_metric_changes),
            "success_metrics": list(self.success_metrics),
            "guardrail_metrics": list(self.guardrail_metrics),
            "test_plan": list(self.test_plan),
            "confidence": self.confidence,
            "status": self.status,
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class ChangeProposal:
    proposal_id: str
    hypothesis_id: str
    candidate_type: str
    target_files: tuple[str, ...]
    target_configs: tuple[str, ...]
    change_summary: str
    expected_behavior_change: str
    risk_level: str
    required_validation: tuple[str, ...]
    rollback_requirements: tuple[str, ...]
    status: str = "PROPOSED"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "hypothesis_id": self.hypothesis_id,
            "candidate_type": self.candidate_type,
            "target_files": list(self.target_files),
            "target_configs": list(self.target_configs),
            "change_summary": self.change_summary,
            "expected_behavior_change": self.expected_behavior_change,
            "risk_level": self.risk_level,
            "required_validation": list(self.required_validation),
            "rollback_requirements": list(self.rollback_requirements),
            "status": self.status,
            "created_at_utc": self.created_at_utc,
        }


class CandidateStatus:
    PROPOSED = "PROPOSED"
    APPROVED_FOR_MATERIALIZATION = "APPROVED_FOR_MATERIALIZATION"
    MATERIALIZING = "MATERIALIZING"
    MATERIALIZED = "MATERIALIZED"
    STATIC_CHECK_PENDING = "STATIC_CHECK_PENDING"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VALIDATED = "VALIDATED"
    READY_FOR_PROMOTION = "READY_FOR_PROMOTION"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    candidate_type: str
    parent_version: str
    champion_version: str
    source_hypothesis_id: str
    source_proposal_id: str
    lineage: tuple[str, ...]
    target_scope: str
    changed_files: tuple[str, ...]
    config_diff: dict
    factor_diff: dict
    strategy_diff: dict
    prompt_diff: dict
    parameter_diff: dict
    code_hash: str
    config_hash: str
    generated_by: str
    generator_model_version: str
    dataset_version: str
    test_spec_version: str
    complexity_impact: dict
    status: str = CandidateStatus.PROPOSED
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "parent_version": self.parent_version,
            "champion_version": self.champion_version,
            "source_hypothesis_id": self.source_hypothesis_id,
            "source_proposal_id": self.source_proposal_id,
            "lineage": list(self.lineage),
            "target_scope": self.target_scope,
            "changed_files": list(self.changed_files),
            "config_diff": dict(self.config_diff),
            "factor_diff": dict(self.factor_diff),
            "strategy_diff": dict(self.strategy_diff),
            "prompt_diff": dict(self.prompt_diff),
            "parameter_diff": dict(self.parameter_diff),
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "generated_by": self.generated_by,
            "generator_model_version": self.generator_model_version,
            "dataset_version": self.dataset_version,
            "test_spec_version": self.test_spec_version,
            "complexity_impact": dict(self.complexity_impact),
            "status": self.status,
            "created_at_utc": self.created_at_utc,
        }
