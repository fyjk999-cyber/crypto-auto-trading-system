"""Phase 3 (Low-Risk V2) recommendation-layer tests.

Proves the evolved ai_decision layer is a recommendation consumer, that
correlated model outputs are not counted as independent facts, that
recommendations carry opposition/reliability/regime/strategy/data-quality
context, and that no execution path exists here.
"""

from __future__ import annotations

import inspect
import math

import pytest

from crypto_trader.ai_decision import conflict, correlation, decision_engine, fusion, recommendation
from crypto_trader.ai_decision.correlation import RollingScoreCorrelation
from crypto_trader.ai_decision.decision_engine import AIDecisionEngine
from crypto_trader.ai_decision.recommendation import RecommendationEngine
from crypto_trader.factors.expert.types import REQUIRED_MODELS


def _model_entry(direction: str, score: float, family: str, index: int) -> dict:
    return {
        "model_id": f"M{index}",
        "model_version": "test",
        "family": family,
        "symbol": "BTCUSDT",
        "timeframes": ["1h"],
        "direction": direction,
        "direction_score": score,
        "confidence": 0.7,
        "theory": "unit fixture",
        "supporting_evidence": ["support"] if direction == "LONG" else [],
        "counter_evidence": ["counter"] if direction == "SHORT" else [],
        "neutral_evidence": [],
        "regime_compatibility": ["TREND_UP"],
        "strategy_compatibility": ["TREND_FOLLOWING"] if direction != "NEUTRAL" else [],
        "data_quality": "HEALTHY",
        "sample_size": 0,
        "reliability_tier": "UNVALIDATED",
    }


def _package(long_count: int, short_count: int, neutral_count: int) -> dict:
    """Build a 25-model package with the requested direction mix."""
    specs = list(REQUIRED_MODELS)
    models: dict[str, dict] = {}
    for index, spec in enumerate(specs):
        if index < long_count:
            direction, score = "LONG", 0.8
        elif index < long_count + short_count:
            direction, score = "SHORT", -0.8
        elif index < long_count + short_count + neutral_count:
            direction, score = "NEUTRAL", 0.0
        else:
            direction, score = "UNAVAILABLE", 0.0
        entry = _model_entry(direction, score, spec.family.value, index)
        entry["model_id"] = spec.model_id
        if direction == "UNAVAILABLE":
            entry["data_quality"] = "UNAVAILABLE"
            entry["unavailable_reason"] = "UNIT_NO_DATA"
            entry["confidence"] = 0.0
        models[spec.model_id] = entry
    return {
        "symbol": "BTCUSDT",
        "regime": "TREND_UP",
        "models": models,
        "costs": {"total_cost_bps": 20.0},
        "authority": "EVIDENCE_ONLY",
        "not_an_order": True,
    }


def test_recommendation_preserves_counts_and_opposition() -> None:
    engine = RecommendationEngine()
    rec = engine.build(_package(long_count=20, short_count=5, neutral_count=0))
    assert rec.long_count == 20
    assert rec.short_count == 5
    assert rec.neutral_count == 0
    assert rec.raw_opposition
    assert rec.strongest_counterarguments
    assert rec.authority == "RECOMMENDATION_ONLY"
    assert rec.not_an_order is True
    assert rec.data_quality == "HEALTHY"
    # 20L/5N must not look like 20L/0S/5N.
    other = RecommendationEngine().build(_package(long_count=20, short_count=0, neutral_count=5))
    assert other.short_count == 0 and other.neutral_count == 5
    assert other.raw_consensus_score != rec.raw_consensus_score
    assert other.suggested_direction != rec.suggested_direction or other.score != rec.score


def test_recommendation_carries_regime_strategy_reliability() -> None:
    rec = RecommendationEngine().build(_package(long_count=15, short_count=5, neutral_count=5))
    assert rec.family_consensus
    assert rec.strategy_fit
    assert set(rec.growth_reliability) == {spec.model_id for spec in REQUIRED_MODELS}
    assert all(
        entry["tier"] == "UNVALIDATED" for entry in rec.growth_reliability.values()
    )
    assert rec.regime_compatibility
    assert rec.correlation["window_days"] == 90
    assert 30 in rec.correlation["reference_windows"] and 90 in rec.correlation["reference_windows"]


def test_unavailable_models_are_reported_not_fabricated() -> None:
    rec = RecommendationEngine().build(_package(long_count=5, short_count=0, neutral_count=0))
    assert rec.unavailable_count == 20
    assert len(rec.degraded_reasons) == 20
    assert all("UNIT_NO_DATA" in reason for reason in rec.degraded_reasons)


def test_correlation_clusters_and_effective_independent_evidence() -> None:
    tracker = RollingScoreCorrelation(window_days=30, min_overlap=8)
    for step in range(30):
        wave = math.sin(step / 3.0)
        tracker.record(
            {
                "A": wave,
                "B": wave,  # perfectly correlated with A
                "C": -wave,  # anti-correlated: same information, inverted
                "D": math.cos(step / 2.0) if step % 2 else -math.cos(step / 2.0),
            }
        )
    assert tracker.correlation("A", "B") == pytest.approx(1.0)
    assert tracker.correlation("A", "C") == pytest.approx(-1.0)
    clusters = tracker.clusters(["A", "B", "C", "D"])
    sizes = sorted(len(cluster) for cluster in clusters)
    assert sizes == [1, 3]
    assert tracker.effective_independent_count(["A", "B", "C", "D"]) == 2
    # Without history the engine reports no independent evidence (fallback path)
    fresh = RollingScoreCorrelation()
    assert fresh.effective_independent_count(["A", "B"]) == 0


def test_recommendation_uses_correlation_adjustment() -> None:
    tracker = RollingScoreCorrelation(window_days=30, min_overlap=4)
    package = _package(long_count=15, short_count=5, neutral_count=5)
    engine = RecommendationEngine(correlation=tracker)
    first = engine.build(package)
    # Record correlated history: all TREND-family members move identically, so
    # the effective independent breadth must not be inflated by them.
    trend_ids = [spec.model_id for spec in REQUIRED_MODELS if spec.family.value == "TREND"]
    for step in range(12):
        tracker.record({model_id: math.sin(step / 3.0) for model_id in trend_ids})
    second = engine.build(package)
    assert second.effective_independent_evidence <= len(second.family_consensus)
    assert second.correlation["history_size"]
    assert first.not_an_order is True and second.not_an_order is True

    # With full 25-model history where everything is correlated, breadth must
    # collapse to a single effective fact.
    collapsed = RollingScoreCorrelation(window_days=30, min_overlap=4)
    all_ids = [spec.model_id for spec in REQUIRED_MODELS]
    for step in range(12):
        collapsed.record({model_id: math.sin(step / 3.0) for model_id in all_ids})
    third = RecommendationEngine(correlation=collapsed).build(package)
    assert third.effective_independent_evidence == 1


def test_existing_decide_api_is_unchanged_and_recommendation_only() -> None:
    engine = AIDecisionEngine()
    result = engine.decide(
        symbol="BTCUSDT",
        quant_decision="LONG",
        quant_confidence=0.8,
        ai_direction="LONG",
        ai_confidence=0.6,
    )
    assert result.decision == "LONG"
    assert result.final_score == pytest.approx(0.72, abs=0.01)
    assert result.authority == "RECOMMENDATION_ONLY"
    assert result.recommendation is None

    from_evidence = engine.decide_from_evidence(
        _package(long_count=20, short_count=0, neutral_count=5)
    )
    assert from_evidence.symbol == "BTCUSDT"
    assert from_evidence.authority == "RECOMMENDATION_ONLY"
    assert from_evidence.recommendation is not None
    assert from_evidence.recommendation["not_an_order"] is True

    neutral = engine.decide_from_evidence(_package(long_count=0, short_count=0, neutral_count=25))
    assert neutral.decision == "NO_TRADE"


def test_recommendation_layer_has_no_execution_path() -> None:
    sources = "\n".join(
        inspect.getsource(module)
        for module in (correlation, decision_engine, fusion, conflict, recommendation)
    )
    for forbidden in (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
        "TradePlan",
        "ExecutionDecision",
    ):
        assert forbidden not in sources, f"recommendation layer must not reference {forbidden}"
