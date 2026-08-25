import asyncio

from crypto_trader.evolution.factor_evolution import FactorEvolutionEngine
from crypto_trader.evolution.knowledge_evolution import KnowledgeEvolutionEngine
from crypto_trader.evolution.optimizer import ResearchOptimizer
from crypto_trader.evolution.research_evolution import ResearchEvolutionEngine
from crypto_trader.intelligence.prediction.evaluator import PredictionEvaluator
from crypto_trader.intelligence.prediction.factor_forecast import FactorForecastEngine
from crypto_trader.intelligence.prediction.regime_forecast import RegimeForecastEngine
from crypto_trader.llm.tools.prediction_intelligence import PredictionIntelligenceTools
from crypto_trader.llm.tools.research_agents import ResearchAgentTools
from crypto_trader.research_agents.supervisor import ResearchSupervisor


def test_research_supervisor_multi_agent():
    supervisor = ResearchSupervisor()
    package = supervisor.run(
        factor_performance={"trend": {"win_rate": "0.6"}},
        regime={"regime": "TRENDING", "confidence": 0.8},
        anomalies=[{"type": "funding_extreme"}],
        volatility=0.3,
        drawdown_env=0.1,
        uncertainty=0.2,
    )
    assert len(package["reports"]) == 3
    assert "consensus" in package
    assert "agent_confidence" in package


def test_research_agent_tools():
    async def run():
        tools = ResearchAgentTools()
        reports = await tools.get_agent_reports(
            factor_performance={"trend": {"win_rate": "0.6"}},
            regime={"regime": "TRENDING", "confidence": 0.8},
        )
        assert reports.ok is True
        consensus = await tools.get_research_consensus()
        assert consensus.ok is True
        confidence = await tools.get_agent_confidence()
        assert confidence.ok is True

    asyncio.run(run())


def test_regime_forecast_and_factor_forecast():
    regime = RegimeForecastEngine().forecast(
        symbol="BTC-USDT", current_regime="TRENDING", trend_strength=0.7, volatility=0.3
    )
    probs = regime.probabilities
    assert abs(sum(probs.values()) - 1.0) < 0.001
    factor = FactorForecastEngine().forecast(
        factor="trend", current_health="HEALTHY", decay_score=0.1, regime_match=0.8
    )
    assert 0 <= factor.degrading_probability <= 1


def test_prediction_evaluator():
    evaluator = PredictionEvaluator()
    evaluator.record({"a": 1}, "a")
    assert evaluator.accuracy() == 1.0


def test_prediction_tools():
    async def run():
        tools = PredictionIntelligenceTools()
        regime = await tools.get_regime_forecast("BTC-USDT", "TRENDING", 0.7, 0.3)
        assert regime.ok is True
        factor = await tools.get_factor_forecast("trend", "HEALTHY", 0.1, 0.8)
        assert factor.ok is True
        conf = await tools.get_research_confidence_forecast("r1", "VALID", 30)
        assert conf.ok is True

    asyncio.run(run())


def test_evolution_engines():
    research = ResearchEvolutionEngine().evaluate(
        research_results=[
            {"factor": "trend", "result": "VALIDATED"},
            {"factor": "momentum", "result": "REJECTED"},
            {"factor": "cvd", "result": "TESTING"},
        ]
    )
    assert "trend" in research.valuable_areas
    assert "momentum" in research.abandoned_areas
    factor = FactorEvolutionEngine().evaluate(
        factor="trend", sample_size=50, win_rate=0.6, sharpe=0.8
    )
    assert factor.stage == "MATURITY"
    knowledge = KnowledgeEvolutionEngine().evaluate(knowledge_id="k1", decay_score=0.6)
    assert knowledge.status == "DEGRADED"
    strategy = ResearchOptimizer().optimize(
        [
            {"research_id": "r1", "value": 0.9, "confidence": 0.8, "novelty": 0.5, "impact": 0.7},
            {"research_id": "r2", "value": 0.2, "confidence": 0.2, "novelty": 0.1, "impact": 0.1},
        ]
    )
    assert strategy.focus_areas[0] == "r1"
