"""Evolution candidate contract foundation.

Contracts only: hypothesis, candidate, and lineage records with a guarded
status state machine. This module implements NO self-modification, NO sandbox
execution, and NO production activation - activation belongs to Safe Promotion.

Frozen dataclasses follow the canonical ``foundation/contracts.py`` pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

# Candidate lifecycle states. Deliberately excludes ACTIVE:
# production activation belongs to Safe Promotion (out of scope here).
CANDIDATE_DRAFT = "DRAFT"
CANDIDATE_MATERIALIZED = "MATERIALIZED"
CANDIDATE_VALIDATING = "VALIDATING"
CANDIDATE_REJECTED = "REJECTED"
CANDIDATE_CERTIFIED = "CERTIFIED"
CANDIDATE_READY_FOR_UPGRADE = "READY_FOR_UPGRADE"

CANDIDATE_STATUSES = (
    CANDIDATE_DRAFT,
    CANDIDATE_MATERIALIZED,
    CANDIDATE_VALIDATING,
    CANDIDATE_REJECTED,
    CANDIDATE_CERTIFIED,
    CANDIDATE_READY_FOR_UPGRADE,
)

# DRAFT -> MATERIALIZED -> VALIDATING -> {REJECTED | CERTIFIED};
# CERTIFIED -> READY_FOR_UPGRADE; REJECTED is terminal.
LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    CANDIDATE_DRAFT: (CANDIDATE_MATERIALIZED,),
    CANDIDATE_MATERIALIZED: (CANDIDATE_VALIDATING,),
    CANDIDATE_VALIDATING: (CANDIDATE_REJECTED, CANDIDATE_CERTIFIED),
    CANDIDATE_REJECTED: (),
    CANDIDATE_CERTIFIED: (CANDIDATE_READY_FOR_UPGRADE,),
    CANDIDATE_READY_FOR_UPGRADE: (),
}

PRODUCTION_ACTIVATION_STATES = frozenset({"ACTIVE", "PROMOTED", "DEPLOYED"})


class IllegalCandidateTransition(ValueError):
    """Raised when a status change is not part of the legal candidate graph."""


def can_transition(current: str, target: str) -> bool:
    return (
        current in LEGAL_TRANSITIONS
        and target in LEGAL_TRANSITIONS
        and target in LEGAL_TRANSITIONS[current]
    )


@dataclass(frozen=True)
class FactorHypothesis:
    """Why a factor/strategy/regime deserves an evolution experiment."""

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

    def __post_init__(self) -> None:
        _require(self.hypothesis_id, "hypothesis_id")
        _require(self.problem_statement, "problem_statement")
        _require(self.expected_mechanism, "expected_mechanism")
        _require(self.proposed_change, "proposed_change")
        if not self.success_metrics:
            raise ValueError("FactorHypothesis requires at least one success metric")
        for name in ("source_lesson_ids", "source_review_ids", "success_metrics",
                     "guardrail_metrics"):
            object.__setattr__(
                self, name, tuple(getattr(self, name))
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
    """A materializable evolution artifact. Cannot activate production."""

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

    def __post_init__(self) -> None:
        required = {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "parent_version": self.parent_version,
            "candidate_version": self.candidate_version,
            "hypothesis_id": self.hypothesis_id,
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "dataset_version": self.dataset_version,
        }
        for name, value in required.items():
            _require(value, name)
        if not self.changed_components:
            raise ValueError("EvolutionCandidate requires at least one changed component")
        if self.status not in CANDIDATE_STATUSES:
            raise ValueError(
                f"invalid candidate status {self.status!r}; "
                f"expected one of {CANDIDATE_STATUSES}"
            )
        object.__setattr__(self, "changed_components", tuple(self.changed_components))

    def transition(self, target_status: str) -> EvolutionCandidate:
        """Return a new instance advanced along the legal status graph."""
        if target_status in PRODUCTION_ACTIVATION_STATES:
            raise IllegalCandidateTransition(
                f"{target_status} is production activation; belongs to Safe Promotion"
            )
        if not can_transition(self.status, target_status):
            raise IllegalCandidateTransition(
                f"illegal candidate transition {self.status} -> {target_status}"
            )
        return replace(self, status=target_status)

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
    """Parent-child provenance entry for a derived candidate."""

    candidate_id: str
    parent_candidate_id: str
    parent_version: str
    hypothesis_id: str
    mutation_type: str
    changed_components: tuple[str, ...]
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        _require(self.candidate_id, "candidate_id")
        # Root candidates may carry parent_candidate_id=""; anything else must link.
        _require(self.mutation_type, "mutation_type")
        if not self.changed_components:
            raise ValueError("lineage record requires changed components")
        object.__setattr__(self, "changed_components", tuple(self.changed_components))

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
    """Walk parent links from ``leaf_candidate_id`` back to the root."""
    by_id = {record.candidate_id: record for record in records}
    chain: list[dict] = []
    seen: set[str] = set()
    cursor = leaf_candidate_id
    while cursor in by_id:
        if cursor in seen:  # defensive: reject cyclic lineage graphs
            raise ValueError(f"cyclic lineage detected at {cursor}")
        seen.add(cursor)
        record = by_id[cursor]
        chain.append(record.to_dict())
        cursor = record.parent_candidate_id
    return chain


def _require(value: str, name: str) -> None:
    if value is None or not str(value).strip():
        raise ValueError(f"required field missing or empty: {name}")
