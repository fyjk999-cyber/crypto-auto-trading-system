from decimal import Decimal

from crypto_trader.factors.attribution import FactorAttribution
from crypto_trader.factors.decay import FactorDecayDetector
from crypto_trader.factors.evaluator import FactorEvaluator
from crypto_trader.factors.models import FactorPerformance
from crypto_trader.factors.performance import FactorPerformanceTracker, TradeObservation
from crypto_trader.llm.context import LLMContextBuilder
from crypto_trader.llm.tools.factor_tools import FactorTools


def make_performance(factor="momentum", sample=300, win=Decimal("0.64"), sharpe=Decimal("1.5")):
    return FactorPerformance(
        factor_name=factor,
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        sample_size=sample,
        win_rate=win,
        average_return=Decimal("0.001"),
        sharpe=sharpe,
        max_drawdown=Decimal("0.05"),
        profit_factor=Decimal("1.8"),
    )


def test_performance_tracker_computes_metrics():
    tracker = FactorPerformanceTracker()
    for _i in range(4):
        tracker.record(TradeObservation("momentum", Decimal("0.5"), Decimal("1"), "WIN"))
    tracker.record(TradeObservation("momentum", Decimal("0.5"), Decimal("-1"), "LOSS"))
    result = tracker.compute("momentum", "BTC-USDT-SWAP")
    assert result["sample_size"] == 5
    assert result["win_rate"] == Decimal("0.8")


def test_factor_evaluator_health_status():
    evaluator = FactorEvaluator()
    healthy = evaluator.evaluate(make_performance())
    assert healthy.status == "HEALTHY"
    experimental = evaluator.evaluate(make_performance(sample=10))
    assert experimental.status == "EXPERIMENTAL"
    degrading = evaluator.evaluate(make_performance(win=Decimal("0.4"), sharpe=Decimal("0.1")))
    assert degrading.status == "DEGRADING"


def test_factor_attribution_positive_and_negative():
    attribution = FactorAttribution()
    result = attribution.attribute(
        trade_id="t1",
        result="WIN",
        pnl_pct=Decimal("2"),
        entry_snapshot={
            "factors": {
                "trend": Decimal("0.8"),
                "momentum": Decimal("0.6"),
                "funding": Decimal("-0.2"),
            }
        },
    )
    assert "trend" in result.contributors
    assert "funding" in result.negative


def test_factor_decay_detector():
    detector = FactorDecayDetector()
    result = detector.detect(
        factor_name="momentum",
        symbol="BTC-USDT-SWAP",
        old_performance=Decimal("0.68"),
        new_performance=Decimal("0.52"),
    )
    assert result.status == "DEGRADING"


def test_llm_context_accepts_factor_health_and_performance():
    ctx = LLMContextBuilder().build(
        symbol="BTC-USDT-SWAP",
        factor_snapshot={"trend": 0.8},
        factor_health={"trend": "HEALTHY"},
        factor_performance={"trend": {"win_rate": "0.6"}},
    )
    assert ctx.factor_health == {"trend": "HEALTHY"}
    assert ctx.factor_performance["trend"]["win_rate"] == "0.6"


def test_factor_tools_evaluation_methods_without_service():
    import asyncio

    tools = FactorTools()
    result = asyncio.run(tools.get_factor_health("momentum", "BTC-USDT-SWAP"))
    assert result.ok is False
    assert result.error == "FACTOR_SERVICE_UNAVAILABLE"
