from decimal import Decimal

from crypto_trader.ai_agents.coordinator import AgentCoordinator
from crypto_trader.alpha_intelligence.alpha_decay import AlphaDecayDetector
from crypto_trader.alpha_intelligence.regime_weight import RegimeWeightEngine
from crypto_trader.execution_intelligence.cost_model import CostModel
from crypto_trader.execution_intelligence.slippage_model import SlippageModel
from crypto_trader.fund_management.allocator import FundAllocator
from crypto_trader.microstructure.orderflow import MarketImpactModel, OrderFlowAnalyzer
from crypto_trader.readiness.checker import LiveReadinessChecker


def test_slippage_and_cost_model():
    slippage = SlippageModel().predict_bps(
        order_size=Decimal("1"),
        orderbook_depth=Decimal("100"),
        spread_bps=Decimal("2"),
        volatility_pct=Decimal("3"),
        liquidity_score=Decimal("80"),
    )
    assert slippage > 0
    cost = CostModel().net_pnl(Decimal("10"), Decimal("1"), Decimal("0.5"), Decimal("0.2"))
    assert cost.net_pnl == Decimal("8.3")


def test_regime_adaptive_weighting():
    engine = RegimeWeightEngine()
    bull = engine.weights_for("BULL")
    assert bull["trend"] > engine.BASE_WEIGHTS["trend"]
    total = sum(bull.values())
    assert abs(total - Decimal("1")) < Decimal("0.001")


def test_alpha_decay_detection():
    detector = AlphaDecayDetector()
    result = detector.detect(
        recent_sharpe=Decimal("0.4"),
        baseline_sharpe=Decimal("1.0"),
        recent_drawdown_pct=Decimal("16"),
        win_rate_change=Decimal("-0.2"),
    )
    assert result.degraded is True
    assert result.weight_multiplier < Decimal("1")


def test_orderflow_and_market_impact():
    flow = OrderFlowAnalyzer().analyze(
        bid_volume="60", ask_volume="40", buy_trades="10", sell_trades="5", large_trades="2"
    )
    assert flow.imbalance == Decimal("20")
    impact = MarketImpactModel().recommended_order_size(orderbook_depth="1000")
    assert impact == Decimal("0.5")


def test_multi_agent_coordinator():
    coordinator = AgentCoordinator()
    decision = coordinator.coordinate(
        market_opinion="LONG", strategy_proposal="LONG", risk_decision="APPROVE"
    )
    assert decision.final_decision == "LONG"
    conflict = coordinator.coordinate(
        market_opinion="LONG", strategy_proposal="SHORT", risk_decision="APPROVE"
    )
    assert conflict.final_decision == "NO_TRADE"
    rejected = coordinator.coordinate(
        market_opinion="LONG", strategy_proposal="LONG", risk_decision="REJECT"
    )
    assert rejected.final_decision == "NO_TRADE"


def test_fund_allocator():
    allocator = FundAllocator()
    allocations = allocator.allocate({"trend": "30", "momentum": "20", "cash": "50"})
    assert len(allocations) == 3
    assert sum((a.weight_pct for a in allocations), Decimal("0")) == Decimal("100")


def test_live_readiness_not_ready_then_ready():
    checker = LiveReadinessChecker()
    not_ready = checker.evaluate(
        shadow_days=10,
        demo_days=10,
        profit_factor=Decimal("1.1"),
        sharpe=Decimal("0.5"),
        max_dd_pct=Decimal("10"),
        uptime_pct=Decimal("99.9"),
        risk_violations=0,
    )
    assert not_ready.status == "NOT_READY"
    ready = checker.evaluate(
        shadow_days=30,
        demo_days=30,
        profit_factor=Decimal("1.5"),
        sharpe=Decimal("1.2"),
        max_dd_pct=Decimal("10"),
        uptime_pct=Decimal("99.9"),
        risk_violations=0,
    )
    assert ready.status == "READY"
