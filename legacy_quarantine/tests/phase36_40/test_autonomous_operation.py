from decimal import Decimal

from crypto_trader.ai_memory.market_memory import MarketMemory
from crypto_trader.alpha_discovery.strategy_generator import StrategyGenerator
from crypto_trader.capital_transition.readiness import CapitalReadiness
from crypto_trader.monitoring.alerts import AlertSystem
from crypto_trader.validation.longterm.metrics import compute_longterm_metrics


def test_longterm_metrics_deterministic():
    metrics = compute_longterm_metrics(
        [Decimal("0.01"), Decimal("0.02"), Decimal("-0.005"), Decimal("0.015")],
        [
            {"result": "CORRECT", "confidence": 0.8, "actual": 1.0},
            {"result": "WRONG", "confidence": 0.9, "actual": 0.0},
        ],
    )
    assert metrics.trade_count == 4
    assert metrics.roi > 0
    assert metrics.max_drawdown >= 0
    assert metrics.direction_accuracy == Decimal("0.5")


def test_ai_market_memory_similarity_no_future_leak():
    memory = MarketMemory()
    memory.store(
        "BTCUSDT",
        {
            "price": "100",
            "volume": "10",
            "volatility": "0.02",
            "funding": "0.0001",
            "oi": "1000",
            "regime": "BULL",
        },
        "LONG",
        "CORRECT",
    )
    similar = memory.find_similar(
        "BTCUSDT",
        {
            "price": "101",
            "volume": "11",
            "volatility": "0.021",
            "funding": "0.0001",
            "oi": "1050",
            "regime": "BULL",
        },
        top_k=1,
    )
    assert len(similar) == 1
    assert similar[0].ai_decision == "LONG"


def test_alpha_discovery_promotion_control():
    generator = StrategyGenerator()
    proposal = generator.generate("p1", "BREAKOUT_OI_FUNDING")
    assert proposal.rules["indicator"] == "breakout"
    assert generator.promote(proposal, ["BACKTEST_PASS"]) is False
    assert (
        generator.promote(proposal, ["BACKTEST_PASS", "WALK_FORWARD_PASS", "SHADOW_PASS"]) is True
    )
    assert proposal.status == "PROMOTED"


def test_monitoring_alerts():
    alerts = AlertSystem()
    fired = alerts.check(
        market_connected=False,
        risk_halted=False,
        drawdown_pct=5,
        exchange_available=True,
        ai_confidence_drift=0.1,
    )
    assert {"alert": "MARKET_DISCONNECTED"} in fired
    fired2 = alerts.check(
        market_connected=True,
        risk_halted=True,
        drawdown_pct=25,
        exchange_available=False,
        ai_confidence_drift=0.4,
    )
    assert {"alert": "RISK_HALTED"} in fired2
    assert {"alert": "DD_WARNING"} in fired2


def test_capital_readiness_not_ready_then_ready():
    readiness = CapitalReadiness()
    result = readiness.evaluate(
        shadow_days=10,
        demo_days=10,
        expectancy=Decimal("0.001"),
        profit_factor=Decimal("1.1"),
        sharpe=Decimal("0.5"),
        max_dd_pct=Decimal("10"),
        risk_violations=0,
        uptime_pct=Decimal("99.9"),
    )
    assert result.ready is False
    assert "SHADOW_DAYS<30" in result.reasons
    result2 = readiness.evaluate(
        shadow_days=30,
        demo_days=30,
        expectancy=Decimal("0.002"),
        profit_factor=Decimal("1.5"),
        sharpe=Decimal("1.2"),
        max_dd_pct=Decimal("10"),
        risk_violations=0,
        uptime_pct=Decimal("99.9"),
    )
    assert result2.ready is True
