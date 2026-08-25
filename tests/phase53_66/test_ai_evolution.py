from decimal import Decimal

from crypto_trader.calibration.engine import DecisionCalibrationEngine
from crypto_trader.committee.coordinator import TradingCommittee
from crypto_trader.learning_coordinator.coordinator import LearningCoordinator
from crypto_trader.memory_graph.graph import MemoryGraph
from crypto_trader.research.anomaly_detector import AnomalyDetector
from crypto_trader.research.market_researcher import MarketResearcher
from crypto_trader.research.regime_detector import RegimeIntelligence
from crypto_trader.strategy_discovery.agent import StrategyDiscoveryAgent
from crypto_trader.style_engine.engine import TradingStyleEngine
from crypto_trader.validation_engine.report import validate_hypothesis


def test_regime_intelligence_classification():
    result = RegimeIntelligence().classify(
        price_change_pct=Decimal("3"),
        volume_ratio=Decimal("1.5"),
        volatility_pct=Decimal("4"),
        funding=Decimal("0.0001"),
        oi_change_pct=Decimal("5"),
        btc_dominance_pct=Decimal("50"),
    )
    assert result.regime == "TREND_BULL"
    assert result.confidence > 0.5


def test_anomaly_detection():
    events = AnomalyDetector().detect(
        symbol="BTCUSDT",
        volume_ratio=4,
        oi_change_pct=25,
        funding=0.002,
        spread_bps=60,
        price_change_pct=9,
    )
    assert any(e.anomaly_type == "VOLUME_SPIKE" for e in events)
    assert any(e.anomaly_type == "FUNDING_EXTREME" for e in events)


def test_market_researcher_report():
    report = MarketResearcher().research(
        regime="TREND_BULL",
        anomalies=[
            AnomalyDetector().detect(
                symbol="BTCUSDT",
                volume_ratio=4,
                oi_change_pct=25,
                funding=0.002,
                spread_bps=60,
                price_change_pct=9,
            )[0]
        ],
        strategy_stats={"trend": 0.6},
        patterns=[
            {"strategy": "trend", "win_rate": 0.6},
            {"strategy": "breakout", "win_rate": 0.3},
        ],
    )
    assert report.market_regime == "TREND_BULL"
    assert "trend" in report.opportunities
    assert "breakout" in report.failed_patterns


def test_strategy_discovery_and_validation():
    hypothesis = StrategyDiscoveryAgent().discover(
        "h1", "SOLUSDT", "HIGH_VOLATILITY", "late breakout"
    )
    assert hypothesis.hypothesis.startswith("Improve")
    report = validate_hypothesis(
        trade_count=50,
        win_rate=Decimal("0.6"),
        profit_factor=Decimal("1.2"),
        max_drawdown=Decimal("10"),
        sharpe=Decimal("1.0"),
        sortino=Decimal("1.0"),
        failure_cases=["false breakout"],
    )
    assert report.status == "EXPERIMENTAL"
    report2 = validate_hypothesis(
        trade_count=120,
        win_rate=Decimal("0.55"),
        profit_factor=Decimal("1.4"),
        max_drawdown=Decimal("12"),
        sharpe=Decimal("1.1"),
        sortino=Decimal("1.2"),
        failure_cases=[],
    )
    assert report2.status == "VALIDATED"


def test_decision_calibration_engine():
    result = DecisionCalibrationEngine().calibrate(
        llm_confidence=Decimal("0.92"),
        historical_accuracy=Decimal("0.55"),
        pattern_confidence=Decimal("0.6"),
        coin_profile_confidence=Decimal("0.5"),
        regime_confidence=Decimal("0.7"),
    )
    assert result.calibrated_confidence < Decimal("0.92")
    assert result.calibrated_confidence > Decimal("0")


def test_trading_style_engine():
    style = TradingStyleEngine().evolve(
        regime="TREND_BEAR", recent_win_rate=Decimal("0.4"), volatility_pct=Decimal("6")
    )
    assert style.style_name == "Conservative Trend Trader"
    assert style.leverage_preference == Decimal("1")


def test_learning_coordinator_and_memory_graph():
    report = LearningCoordinator().run_daily(
        yesterday_trades=[{"symbol": "BTCUSDT", "lesson": "confirm trend"}],
        market_changes=["BTC volume spike"],
        new_patterns=["trend breakout"],
        failed_decisions=["late entry"],
    )
    assert report.trades_analyzed == 1
    assert "BTCUSDT" in report.updated_profiles
    graph = MemoryGraph()
    graph.add_node("BTC", "coin", "BTC")
    graph.add_node("trend_pattern", "pattern", "trend")
    graph.add_node("profit", "outcome", "profit")
    graph.add_edge("BTC", "caused", "trend_pattern")
    graph.add_edge("trend_pattern", "resulted", "profit")
    assert graph.query("BTC", "caused") == ["trend_pattern"]
    assert graph.query("trend_pattern", "resulted") == ["profit"]


def test_trading_committee_debate():
    debate = TradingCommittee().debate(
        research_view="LONG", quant_view="LONG", risk_view="APPROVE", conviction=0.7
    )
    assert debate.final_decision == "LONG"
    debate2 = TradingCommittee().debate(
        research_view="LONG", quant_view="LONG", risk_view="REJECT", conviction=0.7
    )
    assert debate2.final_decision == "NO_TRADE"
