from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.capital_deployment.benchmark import BenchmarkRow, LegacyBenchmarkEngine
from crypto_trader.capital_deployment.emergency import EmergencyDrillRunner
from crypto_trader.capital_deployment.micro_policy import MicroCapitalDeploymentPolicy
from crypto_trader.capital_deployment.readiness import CapitalReadinessEvaluator
from crypto_trader.capital_management.engine import (
    CapitalAllocationContext,
    CapitalAllocationEngine,
)
from crypto_trader.execution_intelligence.liquidity import ExecutionPlanner, LiquidityAssessor
from crypto_trader.portfolio_risk.budget_engine import (
    PortfolioRiskBudget,
    PortfolioRiskEngine,
    PortfolioRiskState,
)
from crypto_trader.shadow_campaign.campaign import CampaignStatus, ShadowCampaignManager


def make_allocation_ctx(**overrides):
    base = dict(
        account_equity=Decimal("100000"),
        available_equity=Decimal("100000"),
        current_cash=Decimal("100000"),
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
        symbol_exposure=Decimal("0"),
        coin_cluster_exposure=Decimal("0"),
        strategy_exposure=Decimal("0"),
        conviction_score=Decimal("0.9"),
        calibrated_confidence=Decimal("0.8"),
        strategy_quality=Decimal("0.8"),
        strategy_lifecycle_state="ACTIVE",
        alpha_decay_state="OK",
        market_regime="TREND_BULL",
        regime_forecast="CONTINUE",
        coin_behavior_profile="TREND_FRIENDLY",
        liquidity_score=Decimal("80"),
        estimated_slippage=Decimal("2"),
        volatility=Decimal("3"),
        drawdown_state=Decimal("0.02"),
        daily_loss_state=Decimal("0"),
        portfolio_risk_budget=Decimal("2000"),
        correlation_risk=Decimal("0.2"),
        transaction_cost_estimate=Decimal("0.001"),
    )
    base.update(overrides)
    return CapitalAllocationContext(**base)


def test_capital_allocation_reduces_for_risk_factors():
    engine = CapitalAllocationEngine()
    normal = engine.allocate("a1", "d1", "BTCUSDT", Decimal("0.04"), make_allocation_ctx())
    low_liq = engine.allocate(
        "a2", "d2", "BTCUSDT", Decimal("0.04"), make_allocation_ctx(liquidity_score=Decimal("20"))
    )
    high_corr = engine.allocate(
        "a3", "d3", "BTCUSDT", Decimal("0.04"), make_allocation_ctx(correlation_risk=Decimal("0.9"))
    )
    degraded = engine.allocate(
        "a4",
        "d4",
        "BTCUSDT",
        Decimal("0.04"),
        make_allocation_ctx(strategy_lifecycle_state="DEGRADING"),
    )
    dd = engine.allocate(
        "a5", "d5", "BTCUSDT", Decimal("0.04"), make_allocation_ctx(drawdown_state=Decimal("0.2"))
    )
    poor_cal = engine.allocate(
        "a6",
        "d6",
        "BTCUSDT",
        Decimal("0.04"),
        make_allocation_ctx(calibrated_confidence=Decimal("0.3")),
    )
    high_cost = engine.allocate(
        "a7",
        "d7",
        "BTCUSDT",
        Decimal("0.04"),
        make_allocation_ctx(transaction_cost_estimate=Decimal("0.005")),
    )
    assert low_liq.recommended_capital_fraction < normal.recommended_capital_fraction
    assert high_corr.recommended_capital_fraction < normal.recommended_capital_fraction
    assert degraded.recommended_capital_fraction < normal.recommended_capital_fraction
    assert dd.recommended_capital_fraction < normal.recommended_capital_fraction
    assert poor_cal.recommended_capital_fraction < normal.recommended_capital_fraction
    assert high_cost.recommended_capital_fraction < normal.recommended_capital_fraction
    # allocator never exceeds hard max
    for decision in (normal, low_liq, high_corr, degraded, dd, poor_cal, high_cost):
        assert decision.recommended_capital_fraction <= Decimal("0.05")


def make_risk_state(**overrides):
    base = dict(
        account_equity=Decimal("100000"),
        cash=Decimal("90000"),
        gross_exposure=Decimal("10000"),
        net_exposure=Decimal("10000"),
        long_exposure=Decimal("10000"),
        short_exposure=Decimal("0"),
        leveraged_exposure=Decimal("10000"),
        symbol_exposure={"SOLUSDT": Decimal("3000")},
        strategy_exposure={"momentum": Decimal("3000")},
        behavior_cluster_exposure={"HIGH_BETA_ALT": Decimal("3000")},
        btc_beta=Decimal("1"),
        market_beta=Decimal("1"),
        correlation_concentration=Decimal("0.3"),
        liquidity_concentration=Decimal("70"),
        volatility_concentration=Decimal("5"),
        drawdown_budget_used=Decimal("1000"),
        daily_loss_budget_used=Decimal("0"),
        open_risk=Decimal("500"),
        pending_order_risk=Decimal("0"),
        version=1,
    )
    base.update(overrides)
    return PortfolioRiskState(**base)


def test_portfolio_risk_detects_hidden_cluster_concentration():
    engine = PortfolioRiskEngine(PortfolioRiskBudget())
    state = make_risk_state(behavior_cluster_exposure={"HIGH_BETA_ALT": Decimal("1800")})
    decision = engine.evaluate_new_risk(
        state=state,
        symbol="SUIUSDT",
        cluster="HIGH_BETA_ALT",
        requested_exposure_delta=Decimal("500"),
        direction="LONG",
    )
    assert "CLUSTER_CONCENTRATION" in decision.reason_codes
    assert decision.decision in ("REDUCE", "REJECT")


def test_portfolio_risk_budget_exhaustion_and_exits():
    engine = PortfolioRiskEngine(PortfolioRiskBudget())
    state = make_risk_state(drawdown_budget_used=Decimal("4500"), open_risk=Decimal("1000"))
    decision = engine.evaluate_new_risk(
        state=state,
        symbol="SOLUSDT",
        cluster="HIGH_BETA_ALT",
        requested_exposure_delta=Decimal("1000"),
        direction="LONG",
    )
    assert "RISK_BUDGET_EXHAUSTED" in decision.reason_codes
    assert decision.decision == "REJECT"
    exit_decision = engine.evaluate_exit(state)
    assert exit_decision.decision == "APPROVE"
    assert state.gross_net_correct() is True


def test_liquidity_and_execution_planning():
    assessor = LiquidityAssessor()
    ok = assessor.assess(
        symbol="BTCUSDT",
        spread_bps=Decimal("2"),
        depth=Decimal("100000"),
        volume_24h=Decimal("1000000"),
        size=Decimal("500"),
        freshness_seconds=0.5,
    )
    assert ok.data_quality == "FRESH"
    stale = assessor.assess(
        symbol="BTCUSDT",
        spread_bps=Decimal("2"),
        depth=Decimal("100000"),
        volume_24h=Decimal("1000000"),
        size=Decimal("500"),
        freshness_seconds=10,
    )
    assert stale.data_quality == "STALE"
    planner = ExecutionPlanner()
    plan = planner.plan(
        assessment=ok,
        order_size=Decimal("10000"),
        spread_bps=Decimal("2"),
        urgent=False,
        thesis_invalidated=False,
    )
    assert plan.style in ("TWAP", "LIMIT", "SPLIT_ORDER")
    urgent_plan = planner.plan(
        assessment=ok,
        order_size=Decimal("100"),
        spread_bps=Decimal("2"),
        urgent=True,
        thesis_invalidated=False,
    )
    assert urgent_plan.time_horizon == "IMMEDIATE"


def test_shadow_campaign_restart_and_no_early_complete():
    campaign = ShadowCampaignManager()
    campaign.start(datetime.now(UTC) - timedelta(days=1))
    assert campaign.record_observation(
        timestamp="2026-01-01T00:00:00+00:00",
        symbol="BTCUSDT",
        regime="BULL",
        is_decision=True,
        is_trade=True,
    )
    assert (
        campaign.record_observation(
            timestamp="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            regime="BULL",
            is_decision=False,
            is_trade=False,
        )
        is False
    )
    # duplicate decision skipped
    assert campaign.record_decision("d1") is True
    assert campaign.record_decision("d1") is False
    # cannot complete early
    status = campaign.maybe_complete(min_elapsed_days=90, min_valid_observation_days=1)
    assert status != CampaignStatus.COMPLETED.value
    # restart resumes
    data = campaign.to_dict()
    restored = ShadowCampaignManager.from_dict(data)
    assert restored.campaign_id == campaign.campaign_id
    assert restored.decision_count == campaign.decision_count


def test_capital_readiness_insufficient_data():
    evaluator = CapitalReadinessEvaluator()
    result = evaluator.evaluate(
        shadow_days=1,
        valid_observation_days=1,
        shadow_trade_count=10,
        profit_factor=Decimal("2"),
        sharpe=Decimal("2"),
        max_drawdown_pct=Decimal("5"),
        calibration_error=Decimal("0.1"),
        operational_uptime=Decimal("99.9"),
        risk_violations=0,
        unresolved_incidents=0,
        data_quality=100,
    )
    assert result.status == "INSUFFICIENT_DATA"
    result2 = evaluator.evaluate(
        shadow_days=95,
        valid_observation_days=80,
        shadow_trade_count=250,
        profit_factor=Decimal("1.5"),
        sharpe=Decimal("1.2"),
        max_drawdown_pct=Decimal("10"),
        calibration_error=Decimal("0.1"),
        operational_uptime=Decimal("99.9"),
        risk_violations=0,
        unresolved_incidents=0,
        data_quality=95,
    )
    assert result2.status == "READY_FOR_MICRO_CAPITAL_REVIEW"


def test_legacy_benchmark_classification():
    engine = LegacyBenchmarkEngine()
    rows = [
        BenchmarkRow(
            timestamp="t1",
            symbol="BTCUSDT",
            legacy_decision="LONG",
            llm_decision="LONG",
            actual_result="LONG",
            classification="",
        ),
        BenchmarkRow(
            timestamp="t2",
            symbol="ETHUSDT",
            legacy_decision="LONG",
            llm_decision="SHORT",
            actual_result="LONG",
            classification="",
        ),
    ]
    result = engine.compare(rows)
    assert result["both_correct"] == 1
    assert result["legacy_correct"] == 1


def test_micro_capital_requires_approval_and_scale_down():
    policy = MicroCapitalDeploymentPolicy()
    result = policy.request_scale_up(
        "STAGE_1_MICRO_CAPITAL",
        approver="human",
        reason="ready",
        min_days=90,
        shadow_days=10,
        risk_violations=0,
        drawdown_pct=Decimal("5"),
        unresolved_incidents=0,
    )
    assert result["approved"] is False
    result = policy.request_scale_up(
        "STAGE_1_MICRO_CAPITAL",
        approver="human",
        reason="ready",
        min_days=90,
        shadow_days=95,
        risk_violations=0,
        drawdown_pct=Decimal("5"),
        unresolved_incidents=0,
    )
    assert result["approved"] is True
    scale_down = policy.scale_down("drawdown breach")
    assert scale_down["reason"] == "SCALED_DOWN"


def test_emergency_drills_no_live_and_kill_switch():
    runner = EmergencyDrillRunner()
    results = runner.run_all()
    assert len(results) == len(runner.ACTION_MAP)
    for drill in results:
        assert drill.no_live_order_submitted is True
        assert drill.no_ledger_corruption is True
        assert drill.kill_switch_authoritative is True
