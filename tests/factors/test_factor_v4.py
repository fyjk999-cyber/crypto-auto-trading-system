import asyncio
from decimal import Decimal

from crypto_trader.factors.anomaly.detector import MarketAnomalyDetector
from crypto_trader.factors.anomaly.history import AnomalyHistory
from crypto_trader.llm.context import LLMContextBuilder
from crypto_trader.llm.tools.factor_research_agent import FactorResearchAgentTools
from crypto_trader.research.experiment_planner import ExperimentPlanner
from crypto_trader.research.hypothesis_agent import HypothesisAgent
from crypto_trader.research.ranking import ResearchRanker


def test_market_anomaly_detector_all_types():
    detector = MarketAnomalyDetector()
    anomalies = detector.detect(
        "BTC-USDT",
        price_change=Decimal("0.001"),
        volume_change=Decimal("-0.2"),
        orderflow=Decimal("0.5"),
        oi_change=Decimal("-0.1"),
        funding=Decimal("0.001"),
        volatility=Decimal("0.8"),
        volatility_previous=Decimal("0.1"),
    )
    types = {a.type for a in anomalies}
    assert {"orderflow_failure", "funding_extreme", "volatility_regime_shift"} <= types
    assert all(0 <= a.severity <= 1 for a in anomalies)


def test_anomaly_history():
    detector = MarketAnomalyDetector()
    history = AnomalyHistory()
    anomalies = detector.detect(
        "BTC-USDT",
        price_change=Decimal("0"),
        volume_change=Decimal("0"),
        orderflow=Decimal("0.5"),
        oi_change=Decimal("0"),
        funding=Decimal("0"),
        volatility=Decimal("0.2"),
        volatility_previous=Decimal("0.2"),
    )
    for anomaly in anomalies:
        history.add(anomaly)
    assert history.count() == len(anomalies)
    assert history.latest("BTC-USDT")


def test_hypothesis_agent_from_orderflow_failure():
    agent = HypothesisAgent()
    hypothesis = agent.generate("h1", {"type": "orderflow_failure", "symbol": "BTC-USDT"})
    assert hypothesis.factor == "orderflow"
    assert "reversal" in hypothesis.question.lower()


def test_experiment_planner():
    plan = ExperimentPlanner().plan(
        {
            "id": "h1",
            "factor": "orderflow",
            "question": "Strong orderflow without price expansion in BTC-USDT may predict reversal",
        }
    )
    assert plan.hypothesis_id == "h1"
    assert plan.evaluation_metric == "win_rate + sharpe"


def test_research_ranker():
    ranked = ResearchRanker().rank(
        [
            {
                "id": "h1",
                "confidence": 0.6,
                "market_relevance": 0.9,
                "data_quality": 0.8,
                "novelty": 0.5,
                "potential_value": 0.7,
            },
            {
                "id": "h2",
                "confidence": 0.2,
                "market_relevance": 0.3,
                "data_quality": 0.3,
                "novelty": 0.2,
                "potential_value": 0.2,
            },
        ]
    )
    assert ranked[0].hypothesis_id == "h1"
    assert ranked[0].rank == 1


def test_llm_research_agent_tools_flow():
    async def run():
        tools = FactorResearchAgentTools()
        anomalies = await tools.get_market_anomalies(
            "BTC-USDT", orderflow=0.5, funding=0.001, volatility=0.8, volatility_previous=0.1
        )
        assert anomalies.ok is True
        assert len(anomalies.data) >= 2
        hypothesis = await tools.generate_hypothesis("h1", anomalies.data[0])
        assert hypothesis.ok is True
        experiment = await tools.create_research_experiment(hypothesis.data)
        assert experiment.ok is True
        priority = await tools.get_research_priority(
            [
                {
                    "id": "h1",
                    "confidence": 0.7,
                    "market_relevance": 0.8,
                    "data_quality": 0.7,
                    "novelty": 0.5,
                    "potential_value": 0.6,
                }
            ]
        )
        assert priority.data[0]["rank"] == 1
        tools.store_report("r1", {"research_id": "r1", "conclusion": "test"})
        report = await tools.get_research_report("r1")
        assert report.data["conclusion"] == "test"

    asyncio.run(run())


def test_llm_context_v4_fields():
    ctx = LLMContextBuilder().build(
        symbol="BTC-USDT",
        market_anomaly={"type": "funding_extreme"},
        active_research={"h1": "OPEN"},
        previous_findings={"r1": "conclusion"},
    )
    assert ctx.market_anomaly["type"] == "funding_extreme"
    assert ctx.active_research["h1"] == "OPEN"
