"""Evolution candidate contract foundation (contracts only, no execution)."""

from crypto_trader.evolution.lab.contracts import (
    CANDIDATE_CERTIFIED,
    CANDIDATE_DRAFT,
    CANDIDATE_MATERIALIZED,
    CANDIDATE_READY_FOR_UPGRADE,
    CANDIDATE_REJECTED,
    CANDIDATE_STATUSES,
    CANDIDATE_VALIDATING,
    LEGAL_TRANSITIONS,
    PRODUCTION_ACTIVATION_STATES,
    CandidateLineageRecord,
    EvolutionCandidate,
    FactorHypothesis,
    IllegalCandidateTransition,
    can_transition,
    lineage_chain,
)

__all__ = [
    "CANDIDATE_CERTIFIED",
    "CANDIDATE_DRAFT",
    "CANDIDATE_MATERIALIZED",
    "CANDIDATE_READY_FOR_UPGRADE",
    "CANDIDATE_REJECTED",
    "CANDIDATE_STATUSES",
    "CANDIDATE_VALIDATING",
    "LEGAL_TRANSITIONS",
    "PRODUCTION_ACTIVATION_STATES",
    "CandidateLineageRecord",
    "EvolutionCandidate",
    "FactorHypothesis",
    "IllegalCandidateTransition",
    "can_transition",
    "lineage_chain",
]
