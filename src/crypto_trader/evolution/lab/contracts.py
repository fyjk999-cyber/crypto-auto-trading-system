"""DEPRECATED compatibility layer for GLM-era lab contracts.

Canonical Candidate authority lives in
``src/crypto_trader/evolution/foundation/``. This module only provides legacy
constructor-shape adapters; it owns no independent lifecycle/state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.evolution.foundation import (
    Candidate,
    CandidateStatus,
    EvolutionHypothesis,
)

# Deprecated legacy status aliases -> canonical CandidateStatus values.
CANDIDATE_DRAFT = CandidateStatus.PROPOSED
CANDIDATE_MATERIALIZED = CandidateStatus.MATERIALIZED
CANDIDATE_VALIDATING = CandidateStatus.VALIDATION_PENDING
CANDIDATE_REJECTED = CandidateStatus.REJECTED
CANDIDATE_CERTIFIED = CandidateStatus.VALIDATED
CANDIDATE_READY_FOR_UPGRADE = CandidateStatus.READY_FOR_PROMOTION

LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {}
PRODUCTION_ACTIVATION_STATES = frozenset({"ACTIVE", "PROMOTED", "DEPLOYED"})

CANDIDATE_STATUSES = tuple(
    dict.fromkeys(
        [
            CANDIDATE_DRAFT,
            CANDIDATE_MATERIALIZED,
            CANDIDATE_VALIDATING,
            CANDIDATE_REJECTED,
            CANDIDATE_CERTIFIED,
            CANDIDATE_READY_FOR_UPGRADE,
        ]
    )
)


class IllegalCandidateTransition(ValueError):
    """Legacy error retained for API compatibility."""


def can_transition(current: str, target: str) -> bool:
    """Legacy helper: always consults canonical CandidateStatus order.

    There is no independent transition graph. The function returns True only
    when target comes after current in the canonical progression.
    """
    canonical_order = (
        CandidateStatus.PROPOSED,
        CandidateStatus.APPROVED_FOR_MATERIALIZATION,
        CandidateStatus.MATERIALIZING,
        CandidateStatus.MATERIALIZED,
        CandidateStatus.VALIDATION_PENDING,
        CandidateStatus.VALIDATED,
        CandidateStatus.REJECTED,
        CandidateStatus.QUARANTINED,
    )
    try:
        return canonical_order.index(current) < canonical_order.index(target)
    except ValueError:
        return False


@dataclass(frozen=True)
class FactorHypothesis:
    """Legacy adapter. Use EvolutionHypothesis for canonical workflows."""

    hypothesis_id: str
    source_lesson_ids: tuple[str, ...]
    source_review_ids: tuple[str, ...]
    target_factor: str
    target_regime: str
    target_strategy: str
    problem_statement: str
    expected_mechanism: str
    proposed_change: str
    expected_benefit: str
    possible_harm: str
    success_metrics: tuple[str, ...]
    guardrail_metrics: tuple[str, ...]
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_canonical(self) -> EvolutionHypothesis:
        return EvolutionHypothesis(
            hypothesis_id=self.hypothesis_id,
            source_intake_id="",
            source_lesson_ids=self.source_lesson_ids,
            source_pattern_ids=(),
            source_research_ids=(),
            scope=self.target_regime,
            target_type="FACTOR",
            target_id=self.target_factor,
            problem_statement=self.problem_statement,
            mechanism=self.expected_mechanism,
            proposed_change=self.proposed_change,
            expected_benefit=self.expected_benefit,
            possible_harm=self.possible_harm,
            predicted_metric_changes={},
            success_metrics=self.success_metrics,
            guardrail_metrics=self.guardrail_metrics,
            test_plan=(),
            confidence=0.5,
        )

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "source_lesson_ids": list(self.source_lesson_ids),
            "source_review_ids": list(self.source_review_ids),
            "target_factor": self.target_factor,
            "target_regime": self.target_regime,
            "target_strategy": self.target_strategy,
            "problem_statement": self.problem_statement,
            "expected_mechanism": self.expected_mechanism,
            "proposed_change": self.proposed_change,
            "expected_benefit": self.expected_benefit,
            "possible_harm": self.possible_harm,
            "success_metrics": list(self.success_metrics),
            "guardrail_metrics": list(self.guardrail_metrics),
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class EvolutionCandidate:
    """Legacy adapter. Use Candidate for canonical workflows.

    No independent transition method exists. Convert with ``to_canonical()``
    and then use canonical CandidateStatus semantics.
    """

    candidate_id: str
    candidate_type: str
    parent_version: str
    candidate_version: str
    hypothesis_id: str
    changed_components: tuple[str, ...]
    code_hash: str
    config_hash: str
    strategy_version: str
    factor_version: str
    model_version: str
    prompt_version: str
    dataset_version: str
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = CANDIDATE_DRAFT

    def to_canonical(self) -> Candidate:
        return Candidate(
            candidate_id=self.candidate_id,
            candidate_type=self.candidate_type,
            parent_version=self.parent_version,
            champion_version=self.parent_version,
            source_hypothesis_id=self.hypothesis_id,
            source_proposal_id="",
            lineage=(self.parent_version,),
            target_scope=",".join(self.changed_components),
            changed_files=(),
            config_diff={},
            factor_diff={"version": self.factor_version} if self.factor_version else {},
            strategy_diff={"version": self.strategy_version} if self.strategy_version else {},
            prompt_diff={"version": self.prompt_version} if self.prompt_version else {},
            parameter_diff={},
            code_hash=self.code_hash,
            config_hash=self.config_hash,
            generated_by="lab-compat",
            generator_model_version="legacy",
            dataset_version=self.dataset_version,
            test_spec_version="legacy",
            complexity_impact={},
            status=self.status,
            created_at_utc=self.created_at_utc,
        )

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "parent_version": self.parent_version,
            "candidate_version": self.candidate_version,
            "hypothesis_id": self.hypothesis_id,
            "changed_components": list(self.changed_components),
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "strategy_version": self.strategy_version,
            "factor_version": self.factor_version,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "dataset_version": self.dataset_version,
            "created_at_utc": self.created_at_utc,
            "status": self.status,
        }


@dataclass(frozen=True)
class CandidateLineageRecord:
    """Legacy read/compat DTO only. Canonical lineage lives in CandidateRegistry."""

    candidate_id: str
    parent_candidate_id: str
    parent_version: str
    hypothesis_id: str
    mutation_type: str
    changed_components: tuple[str, ...]
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "parent_candidate_id": self.parent_candidate_id,
            "parent_version": self.parent_version,
            "hypothesis_id": self.hypothesis_id,
            "mutation_type": self.mutation_type,
            "changed_components": list(self.changed_components),
            "created_at_utc": self.created_at_utc,
        }


def lineage_chain(records: list[CandidateLineageRecord], leaf_candidate_id: str) -> list[dict]:
    """Compatibility helper; canonical lineage authority is CandidateRegistry."""
    by_id = {record.candidate_id: record for record in records}
    chain: list[dict] = []
    seen: set[str] = set()
    cursor = leaf_candidate_id
    while cursor in by_id:
        if cursor in seen:
            raise ValueError(f"cyclic lineage detected at {cursor}")
        seen.add(cursor)
        record = by_id[cursor]
        chain.append(record.to_dict())
        cursor = record.parent_candidate_id
    return chain
