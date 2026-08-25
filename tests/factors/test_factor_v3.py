import asyncio
from decimal import Decimal

from crypto_trader.factors.combinations.evaluator import CombinationEvaluator
from crypto_trader.factors.combinations.generator import CombinationGenerator
from crypto_trader.factors.confidence import FactorConfidenceEngine
from crypto_trader.factors.regime.detector import MarketRegimeDetector
from crypto_trader.factors.regime.history import RegimeHistory
from crypto_trader.llm.context import LLMContextBuilder
from crypto_trader.llm.tools.factor_intelligence_v3 import FactorIntelligenceV3Tools


def test_market_regime_detector_trending():
    detector = MarketRegimeDetector()
    regime = detector.detect(
        "BTC-USDT",
        trend_strength=Decimal("0.7"),
        volatility=Decimal("0.3"),
        volume_change=Decimal("0.2"),
        oi_change=Decimal("0.05"),
        funding=Decimal("0.0001"),
        price_change=Decimal("1"),
    )
    assert regime.regime == "TRENDING"
    assert regime.confidence > 0.5


def test_market_regime_detector_panic():
    detector = MarketRegimeDetector()
    regime = detector.detect(
        "BTC-USDT",
        trend_strength=Decimal("0"),
        volatility=Decimal("0.9"),
        volume_change=Decimal("0"),
        oi_change=Decimal("0"),
        funding=Decimal("0"),
        price_change=Decimal("-8"),
    )
    assert regime.regime == "PANIC"


def test_regime_history_distribution():
    history = RegimeHistory()
    history.add({"symbol": "BTC-USDT", "regime": "TRENDING"})
    history.add({"symbol": "BTC-USDT", "regime": "RANGING"})
    assert history.distribution("BTC-USDT") == {"TRENDING": 1, "RANGING": 1}
    assert history.latest("BTC-USDT")["regime"] == "RANGING"


def test_factor_confidence_engine():
    engine = FactorConfidenceEngine()
    result = engine.compute(
        factor="trend",
        current_value=Decimal("0.8"),
        historical_reliability=Decimal("0.75"),
        regime_match=Decimal("0.9"),
        decay_status="HEALTHY",
    )
    assert result.confidence > 0.5
    degraded = engine.compute(
        factor="momentum",
        current_value=Decimal("0.7"),
        historical_reliability=Decimal("0.7"),
        regime_match=Decimal("0.5"),
        decay_status="DEGRADING",
    )
    assert degraded.confidence < result.confidence


def test_combination_generator_and_evaluator():
    generator = CombinationGenerator()
    combos = generator.generate(["trend", "orderflow", "open_interest", "funding"], 3)
    assert any(set(c) == {"trend", "orderflow", "open_interest"} for c in combos)
    evaluator = CombinationEvaluator()
    observations = [{"result": "WIN"}] * 40 + [{"result": "LOSS"}] * 10
    combination = evaluator.evaluate(
        factors=["trend", "orderflow", "open_interest"], observations=observations
    )
    assert combination.status == "VALIDATED"
    assert combination.performance["win_rate"] == "0.8"


def test_llm_v3_tools():
    async def run():
        tools = FactorIntelligenceV3Tools()
        regime = await tools.get_market_regime(
            "BTC-USDT",
            {
                "market_state": {
                    "trend": "0.7",
                    "volatility": "0.3",
                    "volume": "0.2",
                    "open_interest": "0.05",
                    "funding": "0.0001",
                    "return": "1",
                }
            },
        )
        assert regime.ok is True
        assert regime.data["regime"] == "TRENDING"
        confidence = await tools.get_factor_confidence(
            "trend", Decimal("0.8"), Decimal("0.75"), Decimal("0.9")
        )
        assert confidence.ok is True
        best = await tools.get_best_factor_context(
            "BTC-USDT",
            {
                "market_state": {
                    "trend": "0.7",
                    "volatility": "0.3",
                    "volume": "0.2",
                    "open_interest": "0.05",
                    "funding": "0.0001",
                    "return": "1",
                }
            },
            [{"factor": "trend", "confidence": 0.82}, {"factor": "momentum", "confidence": 0.42}],
        )
        assert best.data["reliable_factors"][0]["factor"] == "trend"
        combo = await tools.analyze_factor_combination(
            ["trend", "orderflow"], [{"result": "WIN"}] * 40
        )
        assert combo.ok is True

    asyncio.run(run())


def test_llm_context_accepts_v3_fields():
    ctx = LLMContextBuilder().build(
        symbol="BTC-USDT",
        market_regime={"regime": "TRENDING"},
        factor_confidence={"trend": {"confidence": "0.82"}},
        factor_combinations={"trend_orderflow": {"status": "VALIDATED"}},
    )
    assert ctx.market_regime["regime"] == "TRENDING"
    assert ctx.factor_confidence["trend"]["confidence"] == "0.82"
