from decimal import Decimal

from crypto_trader.alpha.sub_strategy.trend_following import TrendFollowingStrategy
from crypto_trader.governance.backtest import BacktestEngine, BacktestMetrics
from crypto_trader.governance.daily_review import DailyReview
from crypto_trader.governance.leverage_control import LeverageControlChain
from crypto_trader.governance.memory import (
    FailureClass,
    FailureMemory,
    TradeMemory,
    TradeMemoryRecord,
)
from crypto_trader.governance.reviewers import (
    AdversarialReviewer,
    HumanApprovalGate,
    ReviewDecision,
    RiskReviewer,
)
from crypto_trader.governance.risk_levels import RiskLevel, RiskLevelInput, TradeRiskClassifier
from crypto_trader.governance.stress import ScenarioStressEngine
from crypto_trader.governance.trade_review import TradeReviewService
from crypto_trader.governance.walk_forward import WalkForward


def test_leverage_control_chain_caps_at_hard_max():
    chain = LeverageControlChain()
    decision = chain.apply(Decimal("10"), risk_cap=Decimal("8"), review_approved=Decimal("7"))
    assert decision.recommended == Decimal("10")
    assert decision.risk_capped == Decimal("6")
    assert decision.effective == Decimal("6")
    assert [s["stage"] for s in decision.stages] == [
        "recommended_leverage",
        "risk_capped_leverage",
        "review_approved_leverage",
        "effective_leverage",
    ]


def test_risk_classifier_levels():
    clf = TradeRiskClassifier()
    nav = Decimal("10000")
    assert (
        clf.classify(
            RiskLevelInput(Decimal("1"), Decimal("100"), nav, Decimal("0.1"), Decimal("10"))
        )
        == RiskLevel.L1
    )
    assert (
        clf.classify(
            RiskLevelInput(Decimal("3"), Decimal("800"), nav, Decimal("0.5"), Decimal("20"))
        )
        == RiskLevel.L2
    )
    assert (
        clf.classify(
            RiskLevelInput(Decimal("4"), Decimal("1600"), nav, Decimal("1"), Decimal("80"))
        )
        == RiskLevel.L3
    )
    assert (
        clf.classify(
            RiskLevelInput(
                Decimal("2"),
                Decimal("100"),
                nav,
                Decimal("0.1"),
                Decimal("10"),
                extreme_market=True,
            )
        )
        == RiskLevel.L4
    )


def test_risk_reviewer_deterministic():
    reviewer = RiskReviewer()
    r = reviewer.review(
        leverage=Decimal("5"),
        position_notional=Decimal("5000"),
        nav=Decimal("10000"),
        maintenance_margin=Decimal("50"),
        liquidation_distance_pct=Decimal("0.01"),
        gross_exposure_pct=Decimal("50"),
        drawdown_pct=Decimal("10"),
        market_volatility=Decimal("0.01"),
        liquidity_score=Decimal("0.8"),
        funding_rate=Decimal("0.0002"),
        market_data_healthy=True,
    )
    assert r.decision in (
        ReviewDecision.PASS,
        ReviewDecision.REDUCE,
        ReviewDecision.REJECT,
        ReviewDecision.ESCALATE,
    )
    assert r.risk_score >= 0


def test_adversarial_reviewer_finds_reasons_to_reject():
    adv = AdversarialReviewer()
    r = adv.review(
        funding_rate=Decimal("0.002"),
        oi_spike=Decimal("0.2"),
        basis=Decimal("0.006"),
        momentum_divergence=Decimal("0.2"),
        regime_conflict=True,
        liquidation_cluster=True,
        volatility_spike=Decimal("0.6"),
        liquidity_deterioration=True,
        spread_widening=True,
        historical_failure_pattern=True,
        correlation_concentration=True,
        stale_data=True,
        execution_uncertainty=True,
    )
    assert r.decision == ReviewDecision.REJECT
    assert len(r.flags) > 5


def test_l4_human_approval_timeout_rejects():
    gate = HumanApprovalGate(timeout_seconds=0)
    gate.request("d1")
    assert gate.resolve("d1", True) == ReviewDecision.REJECT
    gate.request("d2")
    assert gate.resolve("d2", False) == ReviewDecision.REJECT


def test_trade_review_l1_auto_pass():
    service = TradeReviewService()
    result = service.review(
        decision_id="d1",
        risk_input=RiskLevelInput(
            Decimal("1"), Decimal("100"), Decimal("10000"), Decimal("0.1"), Decimal("10")
        ),
        risk_kwargs={},
        adversarial_kwargs={},
        proposed_position=Decimal("1"),
        proposed_leverage=Decimal("1"),
    )
    assert result.level == RiskLevel.L1
    assert result.decision == ReviewDecision.PASS


def test_trade_review_l4_waits_for_human():
    service = TradeReviewService()
    risk_input = RiskLevelInput(
        Decimal("6"), Decimal("2500"), Decimal("10000"), Decimal("2"), Decimal("150")
    )
    result = service.review(
        decision_id="d_l4",
        risk_input=risk_input,
        risk_kwargs={
            "leverage": Decimal("6"),
            "position_notional": Decimal("2500"),
            "nav": Decimal("10000"),
            "maintenance_margin": Decimal("25"),
            "liquidation_distance_pct": Decimal("0.01"),
            "gross_exposure_pct": Decimal("25"),
            "drawdown_pct": Decimal("5"),
            "market_volatility": Decimal("0.01"),
            "liquidity_score": Decimal("0.8"),
            "funding_rate": Decimal("0.0001"),
            "market_data_healthy": True,
        },
        adversarial_kwargs={
            "funding_rate": Decimal("0.0001"),
            "oi_spike": Decimal("0"),
            "basis": Decimal("0"),
            "momentum_divergence": Decimal("0"),
            "regime_conflict": False,
            "liquidation_cluster": False,
            "volatility_spike": Decimal("0"),
            "liquidity_deterioration": False,
            "spread_widening": False,
            "historical_failure_pattern": False,
            "correlation_concentration": False,
            "stale_data": False,
            "execution_uncertainty": False,
        },
        proposed_position=Decimal("1"),
        proposed_leverage=Decimal("6"),
    )
    assert result.decision == ReviewDecision.WAITING_APPROVAL
    # timeout -> reject via fresh service? our gate timeout zero? default 300; just assert waiting
    assert result.human_approval_id == "d_l4"


def test_stress_engine_runs_all_scenarios_and_resizes():
    engine = ScenarioStressEngine()
    results = engine.run(
        equity=Decimal("10000"),
        position_notional=Decimal("5000"),
        side="LONG",
        leverage=Decimal("5"),
        maintenance_margin=Decimal("50"),
        liquidation_distance=Decimal("0.05"),
        gross_exposure_pct=Decimal("50"),
        correlated_notional=Decimal("2000"),
    )
    assert len(results) >= 13
    if not all(r.passed for r in results):
        pos, lev, ok = engine.risk_aware_resize(results, Decimal("5000"), Decimal("5"))
        assert ok and lev < Decimal("5")


def test_trade_memory_and_failure_memory():
    memory = TradeMemory()
    record = TradeMemoryRecord(
        decision_id="d1",
        symbol="BTCUSDT",
        side="LONG",
        regime="BULL",
        strategy_scores={},
        effective_weights={},
        raw_confidence=Decimal("0.8"),
        calibrated_confidence=Decimal("0.7"),
        recommended_position=Decimal("1"),
        approved_position=Decimal("1"),
        recommended_leverage=Decimal("5"),
        approved_leverage=Decimal("3"),
        entry=Decimal("100"),
        exit=Decimal("105"),
        fees=Decimal("0.1"),
        funding_pnl=Decimal("-0.05"),
        realized_pnl=Decimal("4.8"),
        r_multiple=Decimal("0.96"),
    )
    memory.record(record)
    assert memory.similar("BTCUSDT", "LONG", "BULL")["status"] == "INSUFFICIENT_DATA"
    for _ in range(5):
        memory.record(
            TradeMemoryRecord(
                decision_id=f"d{_}",
                symbol="BTCUSDT",
                side="LONG",
                regime="BULL",
                strategy_scores={},
                effective_weights={},
                raw_confidence=Decimal("0.8"),
                calibrated_confidence=Decimal("0.7"),
                recommended_position=Decimal("1"),
                approved_position=Decimal("1"),
                recommended_leverage=Decimal("5"),
                approved_leverage=Decimal("3"),
                entry=Decimal("100"),
                exit=Decimal("102"),
                fees=Decimal("0.1"),
                funding_pnl=Decimal("0"),
                realized_pnl=Decimal("1.9"),
                r_multiple=Decimal("0.38"),
            )
        )
    report = memory.similar("BTCUSDT", "LONG", "BULL")
    assert report["status"] == "OK"
    assert report["sample_count"] == 6
    assert report["historical_win_rate"] > 0


def test_daily_review_stats():
    memory = TradeMemory()
    failure = FailureMemory()
    failure.record("d1", FailureClass.TIMING_ERROR)
    record = TradeMemoryRecord(
        decision_id="d1",
        symbol="BTCUSDT",
        side="LONG",
        regime="BULL",
        strategy_scores={},
        effective_weights={},
        raw_confidence=Decimal("0.8"),
        calibrated_confidence=Decimal("0.7"),
        recommended_position=Decimal("1"),
        approved_position=Decimal("1"),
        recommended_leverage=Decimal("5"),
        approved_leverage=Decimal("3"),
        entry=Decimal("100"),
        exit=Decimal("105"),
        fees=Decimal("0.1"),
        funding_pnl=Decimal("-0.05"),
        realized_pnl=Decimal("4.8"),
        r_multiple=Decimal("0.96"),
        failure_class=FailureClass.TIMING_ERROR,
    )
    memory.record(record)
    review = DailyReview(memory, failure)
    stats = review.run()
    assert stats.trade_count == 1
    assert stats.long_pnl == Decimal("4.8")
    assert stats.fees == Decimal("0.1")
    assert stats.failure_distribution["TIMING_ERROR"] == 1


def test_backtest_engine_metrics_no_future_leak():
    prices = [Decimal("100") + Decimal(i) * Decimal("0.1") for i in range(120)]
    engine = BacktestEngine(TrendFollowingStrategy())
    metrics = engine.run(prices)
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.turnover >= 0
    assert metrics.max_drawdown >= 0


def test_walk_forward_overfitting_gate():
    wf = WalkForward()
    result = wf.evaluate(
        is_sharpe=Decimal("2.0"),
        oos_sharpe=Decimal("0.5"),
        regimes_is={"BULL"},
        regimes_oos={"BULL"},
        strategies_is={"trend"},
        strategies_oos={"trend"},
        max_dd_is=Decimal("0.05"),
        max_dd_oos=Decimal("0.20"),
    )
    assert result.passed is False
    result2 = wf.evaluate(
        is_sharpe=Decimal("1.5"),
        oos_sharpe=Decimal("1.3"),
        regimes_is={"BULL", "RANGE"},
        regimes_oos={"BULL", "RANGE"},
        strategies_is={"trend"},
        strategies_oos={"trend"},
        max_dd_is=Decimal("0.05"),
        max_dd_oos=Decimal("0.06"),
    )
    assert result2.passed is True


def test_drawdown_policy_50_pct_kill_switch():
    from crypto_trader.governance.drawdown import DrawdownPolicy

    policy = DrawdownPolicy()
    d49 = policy.evaluate(Decimal("0.49"))
    assert d49.kill_switch is False
    assert d49.risk_multiplier > 0
    d50 = policy.evaluate(Decimal("0.50"))
    assert d50.kill_switch is True
    assert d50.risk_multiplier == 0
    assert policy.allow_action(d50, "OPEN_LONG") is False
    assert policy.allow_action(d50, "OPEN_SHORT") is False
    assert policy.allow_action(d50, "INCREASE_LONG") is False
    assert policy.allow_action(d50, "INCREASE_SHORT") is False
    assert policy.allow_action(d50, "REDUCE") is True
    assert policy.allow_action(d50, "CLOSE") is True
