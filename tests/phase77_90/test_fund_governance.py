from decimal import Decimal

from crypto_trader.ai_research_lab.lab import AIResearchLab
from crypto_trader.ai_skill.evaluator import SkillEvaluator
from crypto_trader.confidence_governor.governor import ConfidenceGovernor
from crypto_trader.fund_simulation.simulator import FundSimulator
from crypto_trader.investment_committee.committee import InvestmentCommittee
from crypto_trader.market_history.encyclopedia import MarketEncyclopedia
from crypto_trader.performance_attribution.engine import AttributionEngine
from crypto_trader.regime_forecast.engine import RegimeForecastEngine
from crypto_trader.risk_personality.engine import RiskPersonalityEngine
from crypto_trader.scorecard.scorer import FundScorecard
from crypto_trader.strategy_portfolio.allocator import StrategyPortfolioAllocator
from crypto_trader.training_scheduler.scheduler import TrainingScheduler


def test_performance_attribution():
    result = AttributionEngine().attribute(
        pnl_pct=Decimal("10"),
        strategy_alpha=Decimal("4"),
        regime_fit=Decimal("3"),
        coin_alpha=Decimal("1"),
        entry_alpha=Decimal("2"),
        exit_alpha=Decimal("1"),
        leverage_effect=Decimal("1"),
        risk_effect=Decimal("1"),
    )
    assert result.strategy_contribution > 0
    assert result.confidence > 0


def test_ai_skill_evaluation():
    score = SkillEvaluator().evaluate(
        regime_accuracy=0.8,
        direction_accuracy=0.7,
        strategy_win_rate=0.6,
        drawdown_score=0.9,
        coin_profile_accuracy=0.75,
        calibration_error=0.2,
    )
    assert 0 <= score.overall <= 1
    assert score.risk_skill == 0.9


def test_confidence_governor_reduces_overconfidence():
    result = ConfidenceGovernor().govern(
        llm_confidence=Decimal("0.9"),
        historical_success=Decimal("0.55"),
        pattern_confidence=Decimal("0.6"),
        coin_profile_confidence=Decimal("0.5"),
        strategy_sharpe=Decimal("1"),
        regime_confidence=Decimal("0.7"),
    )
    assert result.calibrated < result.original


def test_risk_personality_engine():
    personality = RiskPersonalityEngine().evaluate(
        avg_win_rate=Decimal("0.7"), avg_leverage=Decimal("2"), holding_hours=Decimal("24")
    )
    assert personality.style == "CONSERVATIVE"


def test_regime_forecast():
    forecast = RegimeForecastEngine().forecast(
        current_regime="TREND_BULL", trend_strength=0.8, volume_trend=0.5, funding_extreme=0.2
    )
    assert abs(sum(forecast.future_probability.values()) - 1.0) < 0.001


def test_strategy_portfolio_allocation():
    allocations = StrategyPortfolioAllocator().allocate(
        regime="TREND_BULL", strategy_performance={}
    )
    total = sum((a.weight_pct for a in allocations), Decimal("0"))
    assert total == Decimal("100")


def test_ai_research_lab_proposal_only():
    report = AIResearchLab().research(
        hypothesis="funding leads reversal", dataset="futures funding"
    )
    assert report.status == "PROPOSAL"
    assert report.recommendation == "NEEDS_VALIDATION"


def test_market_encyclopedia():
    enc = MarketEncyclopedia()
    enc.add_event(2022, "BEAR", "liquidity collapse")
    assert enc.similar_periods(event_type="BEAR")[0].year == 2022


def test_fund_simulation_and_committee_and_scorecard_and_scheduler():
    sim = FundSimulator().run(months=12, returns=[Decimal("0.01")] * 12)
    assert sim.months == 12
    committee = InvestmentCommittee().decide(
        research_presentation="OPPORTUNITY",
        risk_review="APPROVE",
        quant_view="LONG",
        critic_view="OK",
    )
    assert committee.decision == "APPROVE"
    score = FundScorecard().score(alpha=0.8, risk=0.9, decision_accuracy=0.7, learning=0.8)
    assert score.overall > 0.7
    scheduler = TrainingScheduler()
    assert "review_yesterday_trades" in scheduler.tasks_for("DAILY")
    assert "strategy_retirement" in scheduler.tasks_for("MONTHLY")
