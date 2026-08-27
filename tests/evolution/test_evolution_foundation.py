from crypto_trader.evolution.foundation.contracts import Candidate, EvolutionHypothesis
from crypto_trader.evolution.foundation.intake import evaluate_intake
from crypto_trader.evolution.foundation.policy import EvolutionMutationPolicy
from crypto_trader.evolution.foundation.registry import CandidateRegistry


def make_candidate(
    candidate_id="c1", changed_files=None, config_diff=None, candidate_type="FACTOR_WEIGHT"
):
    return Candidate(
        candidate_id=candidate_id,
        candidate_type=candidate_type,
        parent_version="v1",
        champion_version="v1",
        source_hypothesis_id="h1",
        source_proposal_id="p1",
        lineage=("v1",),
        target_scope="factors",
        changed_files=tuple(changed_files or ["src/crypto_trader/factors/weights.json"]),
        config_diff=config_diff or {"momentum_weight": "0.2"},
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


def test_intake_confirmed_lesson_eligibility():
    assert (
        evaluate_intake(
            evidence_count=3,
            independent_period_count=2,
            contradiction_count=0,
            confidence=0.8,
            source_type="CONFIRMED_LESSON",
        ).status
        == "ELIGIBLE"
    )


def test_intake_weak_one_off_not_eligible():
    assert evaluate_intake(
        evidence_count=1,
        independent_period_count=1,
        contradiction_count=0,
        confidence=0.6,
        source_type="CANDIDATE_LESSON",
    ).status in ("RESEARCH_REQUIRED", "INSUFFICIENT_EVIDENCE")


def test_intake_contradictions_dominate_reject():
    assert (
        evaluate_intake(
            evidence_count=1,
            independent_period_count=1,
            contradiction_count=3,
            confidence=0.6,
            source_type="CANDIDATE_LESSON",
        ).status
        == "REJECTED"
    )


def test_protected_core_rejected():
    policy = EvolutionMutationPolicy()
    candidate = make_candidate(changed_files=["src/crypto_trader/runtime/engine.py"])
    ok, reason = policy.validate(candidate)
    assert ok is False
    assert reason == "PROTECTED_PATH_VIOLATION"


def test_candidate_registry_registers_and_deduplicates():
    registry = CandidateRegistry()
    candidate = make_candidate()
    assert registry.register(candidate) == (True, "REGISTERED")
    assert registry.register(candidate) == (False, "DUPLICATE")
    duplicate = make_candidate("c2")
    assert registry.register(duplicate) == (False, "EQUIVALENT")


def test_candidate_registry_lineage_and_rejection():
    registry = CandidateRegistry()
    candidate = make_candidate()
    registry.register(candidate)
    lineage = registry.get_lineage("c1")
    assert lineage[-1]["candidate_id"] == "c1"
    registry.mark_rejected("c1", "bad backtest")
    assert registry.get("c1").status == "REJECTED"
    assert any(r["reason"] == "bad backtest" for r in registry.rejections)


def test_hypothesis_requires_metrics_and_harm():
    hypothesis = EvolutionHypothesis(
        hypothesis_id="h1",
        source_intake_id="i1",
        source_lesson_ids=("L1",),
        source_pattern_ids=(),
        source_research_ids=(),
        scope="FACTOR",
        target_type="FACTOR_WEIGHT",
        target_id="momentum",
        problem_statement="weak in range",
        mechanism="weight down",
        proposed_change="reduce weight",
        expected_benefit="fewer false longs",
        possible_harm="miss trend starts",
        predicted_metric_changes={},
        success_metrics=("win_rate",),
        guardrail_metrics=("max_dd",),
        test_plan=("backtest",),
        confidence=0.6,
    )
    assert hypothesis.success_metrics
    assert hypothesis.guardrail_metrics
    assert hypothesis.possible_harm
