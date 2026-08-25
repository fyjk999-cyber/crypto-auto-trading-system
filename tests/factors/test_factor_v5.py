import asyncio

from crypto_trader.intelligence.engine import MarketIntelligenceEngine
from crypto_trader.intelligence.knowledge.graph import KnowledgeGraph
from crypto_trader.intelligence.similarity.matcher import SimilarityMatcher
from crypto_trader.intelligence.summary import MarketSummaryEngine
from crypto_trader.llm.context import LLMContextBuilder
from crypto_trader.llm.tools.market_intelligence import MarketIntelligenceTools
from crypto_trader.research.consensus import ResearchConsensusEngine


def test_market_summary_engine():
    summary = MarketSummaryEngine().summarize(
        regime={"regime": "TRENDING", "confidence": 0.8},
        factors={"trend": 0.5, "open_interest": 0.2, "funding": 0.6},
        anomalies=[{"type": "funding_extreme", "severity": 0.8}],
    )
    assert summary.market_state == "TRENDING"
    assert "funding extreme" in summary.risks


def test_research_consensus_engine():
    consensus = ResearchConsensusEngine().consensus(
        [
            {"result": "VALIDATED", "conclusion": "bullish"},
            {"result": "REJECTED", "conclusion": "bearish"},
            {"result": "NEUTRAL", "conclusion": "neutral"},
        ]
    )
    assert "bullish" in consensus["bullish_evidence"]
    assert consensus["conclusion"] == "mixed evidence"


def test_similarity_matcher_explainable():
    matcher = SimilarityMatcher()
    result = matcher.match(
        current_regime="TRENDING",
        current_factors={
            "trend": 0.8,
            "momentum": 0.5,
            "volatility": 0.3,
            "orderflow": 0.4,
            "funding": 0.1,
            "open_interest": 0.2,
        },
        historical_cases=[
            {
                "case_id": "2024-02",
                "regime": "TRENDING",
                "factors": {
                    "trend": 0.7,
                    "momentum": 0.6,
                    "volatility": 0.4,
                    "orderflow": 0.5,
                    "funding": 0.2,
                    "open_interest": 0.3,
                },
                "outcome": "positive",
            },
            {
                "case_id": "2024-10",
                "regime": "RANGING",
                "factors": {
                    "trend": 0.0,
                    "momentum": 0.0,
                    "volatility": 0.2,
                    "orderflow": 0.0,
                    "funding": 0.0,
                    "open_interest": 0.0,
                },
                "outcome": "negative",
            },
        ],
    )
    assert result["similar_cases"][0]["case_id"] == "2024-02"
    assert "positive" in result["outcomes"]


def test_knowledge_graph_query():
    graph = KnowledgeGraph()
    graph.add("TRENDING", "condition_for", "orderflow", {"note": "low funding"})
    graph.add("orderflow", "resulted_in", "positive")
    results = graph.query("orderflow when valid")
    assert len(results) == 2


def test_market_intelligence_engine_build():
    engine = MarketIntelligenceEngine()
    context = engine.build(
        symbol="BTC-USDT",
        regime={"regime": "TRENDING", "confidence": 0.8},
        factors={"trend": 0.5, "open_interest": 0.2, "funding": 0.6},
        factor_confidences={"trend": {"confidence": "0.82"}},
        anomalies=[{"type": "funding_extreme", "severity": 0.8}],
        research=[{"result": "VALIDATED", "conclusion": "bullish"}],
        similar_cases={"outcomes": {"positive": 1}},
    )
    assert context["symbol"] == "BTC-USDT"
    assert context["overall_confidence"] > 0


def test_llm_market_intelligence_tools():
    async def run():
        tools = MarketIntelligenceTools()
        summary = await tools.get_market_summary(
            "BTC-USDT",
            regime={"regime": "TRENDING", "confidence": 0.8},
            factors={"trend": 0.5, "funding": 0.6},
            anomalies=[{"type": "funding_extreme", "severity": 0.8}],
        )
        assert summary.ok is True
        consensus = await tools.get_research_consensus(
            "BTC-USDT", [{"result": "VALIDATED", "conclusion": "bullish"}]
        )
        assert consensus.data["conclusion"] == "bullish tilt"
        similar = await tools.get_similar_market_cases(
            "BTC-USDT",
            current_regime="TRENDING",
            current_factors={
                "trend": 0.8,
                "momentum": 0.5,
                "volatility": 0.3,
                "orderflow": 0.4,
                "funding": 0.1,
                "open_interest": 0.2,
            },
            historical_cases=[
                {
                    "case_id": "c1",
                    "regime": "TRENDING",
                    "factors": {
                        "trend": 0.7,
                        "momentum": 0.6,
                        "volatility": 0.4,
                        "orderflow": 0.5,
                        "funding": 0.2,
                        "open_interest": 0.3,
                    },
                    "outcome": "positive",
                }
            ],
        )
        assert similar.ok is True
        tools.add_knowledge_relation("TRENDING", "condition_for", "orderflow")
        knowledge = await tools.query_market_knowledge("orderflow")
        assert knowledge.ok is True

    asyncio.run(run())


def test_llm_context_v5_fields():
    ctx = LLMContextBuilder().build(
        symbol="BTC-USDT",
        historical_similarity={"similar_cases": []},
        research_consensus={"conclusion": "bullish tilt"},
        market_intelligence_summary={"market_state": "TRENDING"},
    )
    assert ctx.research_consensus["conclusion"] == "bullish tilt"
    assert ctx.market_intelligence_summary["market_state"] == "TRENDING"
