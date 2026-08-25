import asyncio

from crypto_trader.intelligence.context_adapter import AnalysisContextAdapter
from crypto_trader.intelligence.feedback.builder import ResearchFeedbackBuilder
from crypto_trader.intelligence.feedback.interface import ResearchFeedbackInterface
from crypto_trader.intelligence.feedback.validator import FeedbackValidator
from crypto_trader.llm.tools.research_feedback import ResearchFeedbackTools


def test_feedback_builder_validates_factors():
    builder = ResearchFeedbackBuilder()
    feedback = builder.build(
        symbol="BTC-USDT",
        market_intelligence={"market_regime": {"regime": "TRENDING"}},
        factor_confidences={"trend": {"confidence": "0.82"}, "momentum": {"confidence": "0.42"}},
        research_consensus={"conclusion": "bullish tilt", "confidence": 0.7},
        historical_context={"similar_cases": []},
        knowledge_health={"k1": {"status": "VALID"}},
    )
    assert feedback.market_state == "TRENDING"
    assert feedback.validated_factors == ["trend"]
    assert feedback.confidence > 0


def test_feedback_validator_rejects_invalid():
    validator = FeedbackValidator()
    bad = validator.validate(
        feedback_id="f1", feedback={"symbol": "", "validated_factors": [], "confidence": 0}
    )
    assert bad.status == "REJECT"
    ok = validator.validate(
        feedback_id="f2",
        feedback={"symbol": "BTC-USDT", "validated_factors": ["trend"], "confidence": 0.7},
    )
    assert ok.status == "PASS"


def test_feedback_interface_build_and_validate():
    interface = ResearchFeedbackInterface()
    result = interface.build_and_validate(
        symbol="BTC-USDT",
        market_intelligence={"market_regime": {"regime": "TRENDING"}},
        factor_confidences={"trend": {"confidence": "0.82"}},
        research_consensus={"conclusion": "bullish tilt", "confidence": 0.7},
        historical_context={},
        knowledge_health={"k1": {"status": "VALID"}},
    )
    assert result["symbol"] == "BTC-USDT"
    assert result["validated_factors"] == ["trend"]
    assert interface.get("BTC-USDT") is not None


def test_analysis_context_adapter():
    adapter = AnalysisContextAdapter()
    result = adapter.adapt(
        {
            "market_state": "TRENDING",
            "validated_factors": ["trend"],
            "factor_confidence": {"trend": "0.82", "momentum": "0.42"},
            "research_consensus": {"conclusion": "bullish tilt"},
            "risk_notes": [],
            "confidence": 0.7,
        }
    )
    assert result["market"] == "TRENDING"
    assert result["trusted_factors"] == ["trend"]
    assert result["weak_factors"] == ["momentum"]


def test_llm_research_feedback_tools():
    async def run():
        interface = ResearchFeedbackInterface()
        interface.build_and_validate(
            symbol="BTC-USDT",
            market_intelligence={"market_regime": {"regime": "TRENDING"}},
            factor_confidences={"trend": {"confidence": "0.82"}},
            research_consensus={"conclusion": "bullish tilt", "confidence": 0.7},
            historical_context={},
            knowledge_health={"k1": {"status": "VALID"}},
        )
        tools = ResearchFeedbackTools(interface)
        feedback = await tools.get_research_feedback("BTC-USDT")
        assert feedback.ok is True
        reliability = await tools.get_factor_reliability_context("BTC-USDT")
        assert reliability.data["trusted_factors"] == ["trend"]
        view = await tools.get_market_research_view("BTC-USDT")
        assert view.data["market"] == "TRENDING"

    asyncio.run(run())
