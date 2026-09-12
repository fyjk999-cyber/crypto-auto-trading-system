from decimal import Decimal

from crypto_trader.ai_certification.certifier import AICertifier
from crypto_trader.alpha_decay.detector import AlphaDecayDetector
from crypto_trader.blind_market_test.tester import BlindMarketTester
from crypto_trader.human_baseline.benchmark import HumanBaselineBenchmark
from crypto_trader.memory_governance.governor import MemoryGovernor
from crypto_trader.regime_adaptation.tester import RegimeAdaptationTester
from crypto_trader.strategy_lifecycle.lifecycle import StrategyLifecycle
from crypto_trader.validation.walk_forward.engine import WalkForwardEngine


def test_walk_forward_report():
    report = WalkForwardEngine().run(
        period="2023",
        performance=Decimal("15"),
        drawdown=Decimal("5"),
        strategy_used="trend",
        failure_cases=["late entry"],
    )
    assert report.generalization_score > 0


def test_blind_market_test():
    result = BlindMarketTester().evaluate(
        environments=["BULL", "BEAR", "RANGE"],
        results=[
            {"generalization": 0.7, "adaptability": 0.6, "risk_control": 0.8},
            {"generalization": 0.6, "adaptability": 0.7, "risk_control": 0.7},
            {"generalization": 0.5, "adaptability": 0.5, "risk_control": 0.6},
        ],
    )
    assert 0 <= result.overall <= 1


def test_memory_governance_quality():
    low = MemoryGovernor().score(
        sample_size=1, repeatability=0.2, regime_match=0.2, confidence=0.5, outcome_quality=0.8
    )
    high = MemoryGovernor().score(
        sample_size=100, repeatability=0.9, regime_match=0.8, confidence=0.8, outcome_quality=0.9
    )
    assert low.score < high.score


def test_strategy_lifecycle_states():
    lifecycle = StrategyLifecycle()
    lifecycle.set_state("trend", "ACTIVE")
    assert lifecycle.get_state("trend") == "ACTIVE"
    lifecycle.set_state("trend", "DEGRADING")
    assert lifecycle.get_state("trend") == "DEGRADING"


def test_alpha_decay_detection():
    result = AlphaDecayDetector().detect(
        historical_pf=Decimal("2.1"),
        recent_pf=Decimal("1.05"),
        win_rate_change=Decimal("-0.1"),
        drawdown_increase=Decimal("5"),
    )
    assert result.decayed is True
    assert result.weight_multiplier < Decimal("1")


def test_regime_adaptation_tester():
    result = RegimeAdaptationTester().test(
        from_regime="BULL",
        to_regime="BEAR",
        trade_count_change_pct=-0.5,
        strategy_change=True,
        risk_change=True,
        portfolio_change=True,
    )
    assert result.reduced_trading is True
    assert result.portfolio_changed is True


def test_human_baseline_benchmark():
    result = HumanBaselineBenchmark().compare(
        ai_decision_quality=0.8,
        human_decision_quality=0.6,
        ai_risk_return=0.7,
        human_risk_return=0.5,
        ai_consistency=0.9,
        human_consistency=0.7,
    )
    assert result.winner == "AI"


def test_ai_certification():
    certified = AICertifier().certify(
        performance_score=0.8, intelligence_score=0.8, discipline_score=0.9
    )
    assert certified.status == "CERTIFIED"
    weak = AICertifier().certify(
        performance_score=0.4, intelligence_score=0.5, discipline_score=0.6
    )
    assert weak.status == "NOT_CERTIFIED"
