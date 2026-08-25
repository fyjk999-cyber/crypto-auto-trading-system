import asyncio
from decimal import Decimal

from crypto_trader.factors.importance import FactorImportanceEngine
from crypto_trader.factors.lifecycle.manager import FactorLifecycleManager
from crypto_trader.intelligence.knowledge.decay import KnowledgeDecayEngine
from crypto_trader.llm.context import LLMContextBuilder
from crypto_trader.llm.tools.adaptive_intelligence import AdaptiveIntelligenceTools
from crypto_trader.research.priority import ResearchPriorityEngine


def test_factor_lifecycle_transitions():
    manager = FactorLifecycleManager()
    status = manager.evaluate(
        factor="trend",
        current_state="CANDIDATE",
        sample_size=20,
        win_rate=Decimal("0.6"),
        sharpe=Decimal("1.0"),
        decay_status="HEALTHY",
    )
    assert status.state == "TESTING"
    status = manager.evaluate(
        factor="trend",
        current_state=status.state,
        sample_size=40,
        win_rate=Decimal("0.6"),
        sharpe=Decimal("0.8"),
        decay_status="HEALTHY",
    )
    assert status.state == "VALIDATED"
    status = manager.evaluate(
        factor="trend",
        current_state=status.state,
        sample_size=40,
        win_rate=Decimal("0.6"),
        sharpe=Decimal("0.8"),
        decay_status="DEGRADING",
    )
    assert status.state == "WARNING"


def test_research_priority_engine_levels():
    engine = ResearchPriorityEngine()
    high = engine.evaluate(
        research_id="r1",
        market_relevance=0.9,
        anomaly_severity=0.8,
        novelty=0.7,
        confidence=0.6,
        potential_impact=0.9,
    )
    assert high.level == "HIGH"
    low = engine.evaluate(
        research_id="r2",
        market_relevance=0.2,
        anomaly_severity=0.1,
        novelty=0.1,
        confidence=0.1,
        potential_impact=0.1,
    )
    assert low.level == "LOW"


def test_factor_importance_ranking():
    engine = FactorImportanceEngine()
    results = engine.compute(
        [
            {
                "factor": "trend",
                "historical_contribution": "0.8",
                "predictive_stability": "0.7",
                "regime_coverage": "0.9",
                "research_confidence": "0.8",
                "decay_penalty": "0.0",
            },
            {
                "factor": "momentum",
                "historical_contribution": "0.4",
                "predictive_stability": "0.5",
                "regime_coverage": "0.6",
                "research_confidence": "0.5",
                "decay_penalty": "0.2",
            },
        ]
    )
    assert results[0].factor == "trend"
    assert results[0].rank == 1


def test_knowledge_decay_statuses():
    engine = KnowledgeDecayEngine()
    valid = engine.evaluate(
        knowledge_id="k1",
        age_days=10,
        performance_change=0.0,
        regime_change=0.0,
        contradiction_frequency=0.0,
    )
    assert valid.status == "VALID"
    invalid = engine.evaluate(
        knowledge_id="k2",
        age_days=200,
        performance_change=-0.4,
        regime_change=0.9,
        contradiction_frequency=0.8,
    )
    assert invalid.status == "INVALID"


def test_llm_adaptive_tools():
    async def run():
        tools = AdaptiveIntelligenceTools()
        lifecycle = await tools.get_factor_lifecycle(
            "trend",
            current_state="ACTIVE",
            sample_size=100,
            win_rate=Decimal("0.6"),
            sharpe=Decimal("0.8"),
            decay_status="DEGRADING",
        )
        assert lifecycle.data["state"] == "WARNING"
        priority = await tools.get_research_priority(
            "r1",
            market_relevance=0.9,
            anomaly_severity=0.8,
            novelty=0.7,
            confidence=0.6,
            potential_impact=0.9,
        )
        assert priority.data["level"] == "HIGH"
        importance = await tools.get_factor_importance(
            [
                {
                    "factor": "trend",
                    "historical_contribution": "0.8",
                    "predictive_stability": "0.7",
                    "regime_coverage": "0.9",
                    "research_confidence": "0.8",
                    "decay_penalty": "0.0",
                }
            ]
        )
        assert importance.data[0]["rank"] == 1
        health = await tools.get_knowledge_health(
            "k1",
            age_days=10,
            performance_change=0.0,
            regime_change=0.0,
            contradiction_frequency=0.0,
        )
        assert health.data["status"] == "VALID"

    asyncio.run(run())


def test_llm_context_v6_fields():
    ctx = LLMContextBuilder().build(
        symbol="BTC-USDT",
        factor_lifecycle={"trend": "ACTIVE"},
        research_priority={"r1": "HIGH"},
        factor_importance={"trend": {"rank": 1}},
        knowledge_health={"k1": "VALID"},
    )
    assert ctx.factor_lifecycle["trend"] == "ACTIVE"
    assert ctx.knowledge_health["k1"] == "VALID"
