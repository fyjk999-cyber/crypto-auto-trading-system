"""Evolution candidate contract foundation tests (WORKSTREAM G).

Covers serialization, immutability, required-field validation, status
transition legality, lineage chains, and the no-production-activation guard.
"""

import pytest

from crypto_trader.evolution.lab import (
    CANDIDATE_CERTIFIED,
    CANDIDATE_DRAFT,
    CANDIDATE_MATERIALIZED,
    CANDIDATE_READY_FOR_UPGRADE,
    CANDIDATE_REJECTED,
    CANDIDATE_STATUSES,
    CANDIDATE_VALIDATING,
    CandidateLineageRecord,
    EvolutionCandidate,
    FactorHypothesis,
    IllegalCandidateTransition,
    lineage_chain,
)


def make_hypothesis(**overrides) -> FactorHypothesis:
    payload = dict(
        hypothesis_id="hyp-001",
        source_lesson_ids=("lesson-1", "lesson-2"),
        source_review_ids=("review-weekly-2026-W36",),
        target_factor="momentum",
        target_regime="TRENDING",
        target_strategy="llm-strategy",
        problem_statement="momentum loses edge in chop",
        expected_mechanism="regime-gated lookback shortens signal lag",
        proposed_change="adjust momentum window 20 -> 14 when TRENDING",
        expected_benefit="+2% expectancy in trending regimes",
        possible_harm="higher turnover in whipsaw weeks",
        success_metrics=("expectancy_per_trade", "hit_rate"),
        guardrail_metrics=("max_drawdown", "turnover_cap"),
    )
    payload.update(overrides)
    return FactorHypothesis(**payload)


def make_candidate(**overrides) -> EvolutionCandidate:
    payload = dict(
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
    payload.update(overrides)
    return EvolutionCandidate(**payload)


# ------------------------------------------------------------------ hypothesis


def test_factor_hypothesis_serialization_round_trip():
    hyp = make_hypothesis()
    assert FactorHypothesis(**hyp.to_dict()) == hyp


def test_factor_hypothesis_required_fields_reject_empty():
    with pytest.raises(ValueError, match="hypothesis_id"):
        make_hypothesis(hypothesis_id="")
    with pytest.raises(ValueError, match="proposed_change"):
        make_hypothesis(proposed_change="   ")
    with pytest.raises(ValueError, match="success metric"):
        make_hypothesis(success_metrics=())


def test_factor_hypothesis_is_immutable():
    hyp = make_hypothesis()
    with pytest.raises(AttributeError):
        hyp.problem_statement = "mutated"


# ------------------------------------------------------------------- candidate


def test_candidate_serialization_round_trip():
    cand = make_candidate(status=CANDIDATE_VALIDATING)
    restored = EvolutionCandidate(**cand.to_dict())
    assert restored == cand
    payload = cand.to_dict()
    assert set(payload) == {
        "candidate_id", "candidate_type", "parent_version", "candidate_version",
        "hypothesis_id", "changed_components", "code_hash", "config_hash",
        "strategy_version", "factor_version", "model_version", "prompt_version",
        "dataset_version", "created_at_utc", "status",
    }


def test_candidate_is_immutable_but_transitions_return_new_instance():
    cand = make_candidate()
    with pytest.raises(AttributeError):
        cand.status = CANDIDATE_MATERIALIZED
    advanced = cand.transition(CANDIDATE_MATERIALIZED)
    assert cand.status == CANDIDATE_DRAFT          # original untouched
    assert advanced.status == CANDIDATE_MATERIALIZED
    assert advanced.candidate_id == cand.candidate_id


def test_candidate_requires_fields_and_known_status():
    with pytest.raises(ValueError, match="code_hash"):
        make_candidate(code_hash="")
    with pytest.raises(ValueError, match="changed component"):
        make_candidate(changed_components=())
    with pytest.raises(ValueError, match="invalid candidate status"):
        make_candidate(status="SOME_WEIRD_STATE")
    # ACTIVE is not part of the candidate vocabulary at all
    assert "ACTIVE" not in CANDIDATE_STATUSES
    with pytest.raises(ValueError, match="invalid candidate status"):
        make_candidate(status="ACTIVE")


def test_candidate_full_legal_lifecycle():
    cand = make_candidate()
    walk = [CANDIDATE_DRAFT, CANDIDATE_MATERIALIZED, CANDIDATE_VALIDATING,
            CANDIDATE_CERTIFIED, CANDIDATE_READY_FOR_UPGRADE]
    current = cand
    for target in walk[1:]:
        current = current.transition(target)
        assert current.status == target
    assert current.to_dict()["status"] == CANDIDATE_READY_FOR_UPGRADE


def test_candidate_illegal_transitions_are_rejected():
    cand = make_candidate()
    for illegal in (CANDIDATE_VALIDATING, CANDIDATE_REJECTED, CANDIDATE_CERTIFIED,
                    CANDIDATE_READY_FOR_UPGRADE):
        with pytest.raises(IllegalCandidateTransition):
            cand.transition(illegal)
    materialized = cand.transition(CANDIDATE_MATERIALIZED)
    with pytest.raises(IllegalCandidateTransition):      # cannot skip VALIDATING
        materialized.transition(CANDIDATE_CERTIFIED)
    rejected = materialized.transition(CANDIDATE_VALIDATING).transition(
        CANDIDATE_REJECTED
    )
    with pytest.raises(IllegalCandidateTransition):      # REJECTED is terminal
        rejected.transition(CANDIDATE_CERTIFIED)
    certified_ready = (
        cand.transition(CANDIDATE_MATERIALIZED)
        .transition(CANDIDATE_VALIDATING)
        .transition(CANDIDATE_CERTIFIED)
        .transition(CANDIDATE_READY_FOR_UPGRADE)
    )
    with pytest.raises(IllegalCandidateTransition):      # upgrade-ready is terminal
        certified_ready.transition(CANDIDATE_DRAFT)


def test_candidate_cannot_activate_production():
    cand = make_candidate()
    for activation_state in ("ACTIVE", "PROMOTED", "DEPLOYED"):
        with pytest.raises(IllegalCandidateTransition, match="Safe Promotion"):
            cand.transition(activation_state)
    serializable = {p["status"] for p in [make_candidate().to_dict()]}
    assert serializable <= set(CANDIDATE_STATUSES)
    assert not {"ACTIVE"} & set(CANDIDATE_STATUSES)


def test_candidate_validation_branch_tracks_hypothesis():
    hyp = make_hypothesis()
    cand = make_candidate(hypothesis_id=hyp.hypothesis_id).transition(
        CANDIDATE_MATERIALIZED
    ).transition(CANDIDATE_VALIDATING).transition(CANDIDATE_REJECTED)
    assert cand.hypothesis_id == hyp.hypothesis_id == "hyp-001"
    assert cand.status == CANDIDATE_REJECTED


# --------------------------------------------------------------------- lineage


def test_lineage_record_round_trip_and_root_allowed_without_parent():
    root = CandidateLineageRecord(
        candidate_id="cand-root",
        parent_candidate_id="",
        parent_version="factorset-v1",
        hypothesis_id="hyp-000",
        mutation_type="INITIAL",
        changed_components=("factors.set",),
    )
    assert root.to_dict()["parent_candidate_id"] == ""
    with pytest.raises(ValueError, match="mutation_type"):
        CandidateLineageRecord(
            candidate_id="x", parent_candidate_id="", parent_version="v",
            hypothesis_id="h", mutation_type="", changed_components=("a",),
        )
    with pytest.raises(ValueError, match="changed components"):
        CandidateLineageRecord(
            candidate_id="x", parent_candidate_id="", parent_version="v",
            hypothesis_id="h", mutation_type="MUTATE", changed_components=(),
        )


def test_lineage_chain_walks_parents_to_root_in_order():
    records = [
        CandidateLineageRecord(
            candidate_id="cand-003",
            parent_candidate_id="cand-002",
            parent_version="factorset-v2-cand",
            hypothesis_id="hyp-002",
            mutation_type="PARAMETER_TUNING",
            changed_components=("factors.momentum.threshold",),
        ),
        CandidateLineageRecord(
            candidate_id="cand-002",
            parent_candidate_id="cand-root",
            parent_version="factorset-v1",
            hypothesis_id="hyp-001",
            mutation_type="PARAMETER_TUNING",
            changed_components=("factors.momentum.parameters.window",),
        ),
        CandidateLineageRecord(
            candidate_id="cand-root",
            parent_candidate_id="",
            parent_version="factorset-v1",
            hypothesis_id="hyp-000",
            mutation_type="INITIAL",
            changed_components=("factors.set",),
        ),
    ]
    chain = lineage_chain(records, leaf_candidate_id="cand-003")
    assert [entry["candidate_id"] for entry in chain] == [
        "cand-003", "cand-002", "cand-root",
    ]
    assert chain[-1]["mutation_type"] == "INITIAL"


def test_lineage_chain_detects_cycles():
    cyclic = [
        CandidateLineageRecord(
            candidate_id="a", parent_candidate_id="b", parent_version="v0",
            hypothesis_id="h", mutation_type="MUTATE", changed_components=("a",),
        ),
        CandidateLineageRecord(
            candidate_id="b", parent_candidate_id="a", parent_version="v1",
            hypothesis_id="h", mutation_type="MUTATE", changed_components=("b",),
        ),
    ]
    with pytest.raises(ValueError, match="cyclic lineage"):
        lineage_chain(cyclic, leaf_candidate_id="a")
