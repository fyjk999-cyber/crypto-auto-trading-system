"""Pre-flight canonical candidate contract hardening tests."""

from dataclasses import FrozenInstanceError

import pytest

from crypto_trader.evolution.foundation import (
    Candidate,
    CandidateRegistry,
    CandidateStatus,
    EvolutionMutationPolicy,
)


def make_candidate(candidate_id="c1", **overrides):
    payload = dict(
        candidate_id=candidate_id,
        candidate_type="FACTOR_WEIGHT",
        parent_version="v1",
        champion_version="v1",
        source_hypothesis_id="h1",
        source_proposal_id="p1",
        lineage=("v1",),
        target_scope="factors",
        changed_files=("src/crypto_trader/factors/weights.json",),
        config_diff={"momentum_weight": "0.2"},
        factor_diff={},
        strategy_diff={},
        prompt_diff={},
        parameter_diff={},
        code_hash="abc",
        config_hash="def",
        generated_by="research_agent",
        generator_model_version="1",
        dataset_version="d1",
        test_spec_version="t1",
        complexity_impact={"new_parameters": 1},
    )
    payload.update(overrides)
    return Candidate(**payload)


def test_candidate_is_frozen_immutable():
    candidate = make_candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.status = CandidateStatus.VALIDATED
    with pytest.raises(FrozenInstanceError):
        candidate.code_hash = "tampered"


def test_candidate_to_dict_round_trip():
    candidate = make_candidate()
    payload = candidate.to_dict()
    restored = Candidate(**payload)
    assert restored.candidate_id == candidate.candidate_id
    assert restored.code_hash == candidate.code_hash
    assert restored.config_hash == candidate.config_hash
    assert tuple(restored.lineage) == candidate.lineage
    assert tuple(restored.changed_files) == candidate.changed_files


def test_production_active_not_a_candidate_state():
    canonical_states = {
        CandidateStatus.PROPOSED,
        CandidateStatus.APPROVED_FOR_MATERIALIZATION,
        CandidateStatus.MATERIALIZING,
        CandidateStatus.MATERIALIZED,
        CandidateStatus.STATIC_CHECK_PENDING,
        CandidateStatus.VALIDATION_PENDING,
        CandidateStatus.VALIDATED,
        CandidateStatus.READY_FOR_PROMOTION,
        CandidateStatus.REJECTED,
        CandidateStatus.QUARANTINED,
    }
    assert "ACTIVE" not in canonical_states
    assert "PROMOTED" not in canonical_states
    assert "ROLLED_BACK" not in canonical_states


def test_candidate_lineage_is_canonical_registry_authority():
    registry = CandidateRegistry()
    parent = make_candidate("v1", code_hash="parent_hash", config_hash="parent_cfg")
    candidate = make_candidate(
        "c_lin",
        lineage=("v1",),
        code_hash="child_hash",
        config_hash="child_cfg",
        parent_version="v1",
    )
    assert registry.register(parent)[0] is True
    assert registry.register(candidate) == (True, "REGISTERED")
    lineage = registry.get_lineage("c_lin")
    assert lineage[-1]["candidate_id"] == "c_lin"
    assert lineage[0]["candidate_id"] == "v1"


def test_duplicate_candidate_control():
    registry = CandidateRegistry()
    candidate = make_candidate("c_dup")
    assert registry.register(candidate)[0] is True
    assert registry.register(candidate) == (False, "DUPLICATE")
    equivalent = make_candidate("c_dup_equiv")
    assert registry.register(equivalent) == (False, "EQUIVALENT")


def test_rejected_candidate_recorded():
    registry = CandidateRegistry()
    candidate = make_candidate("c_rej")
    registry.register(candidate)
    registry.mark_rejected("c_rej", "backtest_guardrail_failure")
    assert registry.get("c_rej").status == CandidateStatus.REJECTED
    assert any(
        record["candidate_id"] == "c_rej" and record["reason"] == "backtest_guardrail_failure"
        for record in registry.rejections
    )


def test_protected_core_policy_blocks_candidate():
    policy = EvolutionMutationPolicy()
    candidate = make_candidate(
        "c_protected", changed_files=("src/crypto_trader/runtime/engine.py",)
    )
    assert policy.validate(candidate) == (False, "PROTECTED_PATH_VIOLATION")


def test_quarantine_state_exists_and_registry_can_mark():
    registry = CandidateRegistry()
    candidate = make_candidate("c_quar")
    registry.register(candidate)
    registry.mark_quarantined("c_quar")
    assert registry.get("c_quar").status == CandidateStatus.QUARANTINED
