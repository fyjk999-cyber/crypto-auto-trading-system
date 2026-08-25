from decimal import Decimal

from crypto_trader.ai.analyst.market_analyzer import MarketAnalyzer
from crypto_trader.ai.context_builder import AIContextBuilder
from crypto_trader.ai.evaluation import PredictionEvaluator
from crypto_trader.ai.memory import AIPredictionMemory, AIPredictionRecord
from crypto_trader.ai_decision.decision_engine import AIDecisionEngine
from crypto_trader.ai_risk.reviewer import AIRiskCommittee
from crypto_trader.exchange_intelligence.price_aggregator import ExchangeQuote, PriceAggregator
from crypto_trader.portfolio.allocator import Allocator
from crypto_trader.portfolio.capital import distribute_capital
from crypto_trader.portfolio.correlation import CorrelationEngine
from crypto_trader.portfolio.exposure import ExposureEngine


def test_ai_analyst_opinion_schema_and_no_trade():
    ctx = AIContextBuilder().build(
        symbol="BTCUSDT",
        feature_vector={"regime": "BULL", "roc5": 0.01, "rsi14": 55},
        opportunity={"side": "LONG"},
        regime="BULL",
    )
    opinion = MarketAnalyzer().analyze(ctx)
    assert opinion.symbol == "BTCUSDT"
    assert opinion.direction_bias in ("LONG", "SHORT", "NEUTRAL")
    assert 0 <= opinion.confidence <= 1


def test_ai_prediction_memory_and_evaluation():
    memory = AIPredictionMemory()
    record = AIPredictionRecord(
        prediction_id="p1", symbol="BTCUSDT", direction="LONG", confidence=0.8
    )
    memory.store(record)
    evaluator = PredictionEvaluator()
    assert evaluator.evaluate(record, "LONG") == "SUCCESS"
    assert memory.get("p1").actual_result == 1.0
    record2 = AIPredictionRecord(
        prediction_id="p2", symbol="BTCUSDT", direction="SHORT", confidence=0.7
    )
    memory.store(record2)
    assert evaluator.evaluate(record2, "LONG") == "FALSE_SHORT"
    cal = evaluator.calibrate(memory.all())
    assert cal.total == 2


def test_ai_decision_long_short_conflict():
    engine = AIDecisionEngine()
    decision = engine.decide(
        symbol="BTCUSDT",
        quant_decision="LONG",
        quant_confidence=0.8,
        ai_direction="LONG",
        ai_confidence=0.6,
    )
    assert decision.decision == "LONG"
    conflict = engine.decide(
        symbol="ETHUSDT",
        quant_decision="LONG",
        quant_confidence=0.8,
        ai_direction="SHORT",
        ai_confidence=0.9,
    )
    assert conflict.decision == "NO_TRADE"
    no_trade = engine.decide(
        symbol="SOLUSDT",
        quant_decision="NO_TRADE",
        quant_confidence=0.0,
        ai_direction="NEUTRAL",
        ai_confidence=0.0,
    )
    assert no_trade.decision == "NO_TRADE"


def test_ai_risk_committee():
    committee = AIRiskCommittee()
    approved = committee.review(
        leverage=Decimal("3"),
        position_pct=Decimal("5"),
        drawdown_pct=Decimal("5"),
        asset_category="LARGE_CAP",
        volatility_pct=Decimal("3"),
        loss_streak=0,
    )
    assert approved.decision == "APPROVE"
    reduced = committee.review(
        leverage=Decimal("6"),
        position_pct=Decimal("5"),
        drawdown_pct=Decimal("5"),
        asset_category="LARGE_CAP",
        volatility_pct=Decimal("3"),
        loss_streak=0,
    )
    assert reduced.decision == "REDUCE"
    rejected = committee.review(
        leverage=Decimal("3"),
        position_pct=Decimal("5"),
        drawdown_pct=Decimal("20"),
        asset_category="LARGE_CAP",
        volatility_pct=Decimal("3"),
        loss_streak=0,
    )
    assert rejected.decision == "REJECT"


def test_portfolio_allocator_exposure_capital():
    allocator = Allocator()
    allocations = allocator.allocate(
        [
            {"symbol": "BTCUSDT", "category": "LARGE_CAP"},
            {"symbol": "PEPEUSDT", "category": "MEME"},
        ]
    )
    assert len(allocations) == 2
    capital = distribute_capital(Decimal("10000"), allocations)
    assert sum(capital.values()) == Decimal("10000")
    exposure = ExposureEngine().calculate(
        [
            {"symbol": "BTCUSDT", "notional": "1000", "strategy": "trend"},
            {"symbol": "ETHUSDT", "notional": "500", "strategy": "momentum"},
        ]
    )
    assert exposure.total_exposure == Decimal("1500")
    assert exposure.asset_concentration["BTCUSDT"] > Decimal("60")


def test_correlation_engine():
    engine = CorrelationEngine()
    corr = engine.correlation_proxy(
        [Decimal("0.1"), Decimal("0.2"), Decimal("0.1")],
        [Decimal("0.1"), Decimal("0.2"), Decimal("0.1")],
    )
    assert corr == Decimal("1")


def test_exchange_price_aggregator_recommendation():
    quotes = [
        ExchangeQuote("OKX", "BTC-USDT-SWAP", Decimal("100"), Decimal("1.5"), Decimal("100")),
        ExchangeQuote("BINANCE", "BTCUSDT", Decimal("100.1"), Decimal("0.8"), Decimal("120")),
        ExchangeQuote("BYBIT", "BTCUSDT", Decimal("99.9"), Decimal("2.0"), Decimal("80")),
    ]
    rec = PriceAggregator().aggregate(quotes)
    assert rec.recommended_exchange == "BINANCE"
    assert rec.best_spread_bps == Decimal("0.8")
