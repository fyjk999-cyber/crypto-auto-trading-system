"""Canonical candidate authority + legacy lab compatibility tests."""

from crypto_trader.evolution.foundation import Candidate, CandidateRegistry, CandidateStatus
from crypto_trader.evolution.lab import (
    CandidateLineageRecord,
    EvolutionCandidate,
    FactorHypothesis,
    lineage_chain,
)


def test_lab_is_compatibility_only_no_transition_method():
    assert not hasattr(EvolutionCandidate, "transition")
    assert "LEGAL_TRANSITIONS" not in dir()
    from crypto_trader.evolution.lab import contracts as lab_contracts

    source = __import__("pathlib").Path(lab_contracts.__file__).read_text()
    assert "LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {}" in source
    assert "def transition(" not in source


def test_lab_factor_hypothesis_maps_to_canonical():
    legacy = FactorHypothesis(
        hypothesis_id="hyp-001",
        source_lesson_ids=("lesson-1",),
        source_review_ids=("review-weekly-2026-W36",),
        target_factor="momentum",
        target_regime="TRENDING",
        target_strategy="llm-strategy",
        problem_statement="momentum loses edge in chop",
        expected_mechanism="regime-gated lookback shortens signal lag",
        proposed_change="adjust momentum window 20 -> 14",
        expected_benefit="+2% expectancy",
        possible_harm="higher turnover",
        success_metrics=("expectancy_per_trade",),
        guardrail_metrics=("max_drawdown",),
    )
    canonical = legacy.to_canonical()
    assert canonical.hypothesis_id == "hyp-001"
    assert canonical.target_type == "FACTOR"
    assert canonical.success_metrics == ("expectancy_per_trade",)


def test_lab_candidate_maps_to_canonical():
    legacy = EvolutionCandidate(
        candidate_id="cand-002",
        candidate_type="FACTOR_PARAMETER",
        parent_version="factorset-v1",
        candidate_version="factorset-v2-cand",
        hypothesis_id="hyp-001",
        changed_components=("factors.momentum.parameters.window",),
        code_hash="abc123",
        config_hash="def456",
        strategy_version="strategy-v3",
        factor_version="factor-v11",
        model_version="model-7",
        prompt_version="prompt-4",
        dataset_version="datasets-2026-08",
    )
    canonical = legacy.to_canonical()
    assert isinstance(canonical, Candidate)
    assert canonical.candidate_id == "cand-002"
    assert canonical.code_hash == "abc123"


def test_canonical_registry_accepts_canonical_only():
    registry = CandidateRegistry()
    legacy = EvolutionCandidate(
        candidate_id="cand-003",
        candidate_type="FACTOR_PARAMETER",
        parent_version="v1",
        candidate_version="v2",
        hypothesis_id="h1",
        changed_components=("f",),
        code_hash="c",
        config_hash="d",
        strategy_version="s",
        factor_version="f",
        model_version="m",
        prompt_version="p",
        dataset_version="ds",
    )
    canonical = legacy.to_canonical()
    ok, reason = registry.register(canonical)
    assert ok is True, reason
    assert registry.get("cand-003").candidate_id == "cand-003"


def test_canonical_status_is_single_authority():
    assert CandidateStatus.VALIDATED
    assert CandidateStatus.PROPOSED
    assert "ACTIVE" not in (
        CandidateStatus.PROPOSED,
        CandidateStatus.APPROVED_FOR_MATERIALIZATION,
        CandidateStatus.MATERIALIZING,
        CandidateStatus.MATERIALIZED,
        CandidateStatus.STATIC_CHECK_PENDING,
        CandidateStatus.VALIDATION_PENDING,
        CandidateStatus.REJECTED,
        CandidateStatus.QUARANTINED,
    )


def test_legacy_lineage_chain_helper():
    records = [
        CandidateLineageRecord("c1", "", "v1", "h", "add", ("f",)),
        CandidateLineageRecord("c2", "c1", "v1", "h", "tune", ("g",)),
    ]
    chain = lineage_chain(records, "c2")
    assert [r["candidate_id"] for r in chain] == ["c2", "c1"]
