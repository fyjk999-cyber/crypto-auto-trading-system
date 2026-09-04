"""Performance smoke test: deterministic, no external services."""
from __future__ import annotations

import time
from decimal import Decimal

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


def make_ctx():
    return CapitalAllocationContext(
        account_equity=Decimal("100000"), available_equity=Decimal("100000"),
        current_cash=Decimal("100000"), gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"), symbol_exposure=Decimal("0"),
        coin_cluster_exposure=Decimal("0"), strategy_exposure=Decimal("0"),
        conviction_score=Decimal("0.8"), calibrated_confidence=Decimal("0.7"),
        strategy_quality=Decimal("0.8"), strategy_lifecycle_state="ACTIVE",
        alpha_decay_state="OK", market_regime="TREND_BULL",
        regime_forecast="CONTINUE", coin_behavior_profile="TREND_FRIENDLY",
        liquidity_score=Decimal("80"), estimated_slippage=Decimal("2"),
        volatility=Decimal("3"), drawdown_state=Decimal("0.02"),
        daily_loss_state=Decimal("0"), portfolio_risk_budget=Decimal("2000"),
        correlation_risk=Decimal("0.2"), transaction_cost_estimate=Decimal("0.001"),
    )


def make_state():
    return PortfolioRiskState(
        account_equity=Decimal("100000"), cash=Decimal("90000"),
        gross_exposure=Decimal("10000"), net_exposure=Decimal("10000"),
        long_exposure=Decimal("10000"), short_exposure=Decimal("0"),
        leveraged_exposure=Decimal("10000"), symbol_exposure={},
        strategy_exposure={}, behavior_cluster_exposure={"HIGH_BETA_ALT": Decimal("3000")},
        btc_beta=Decimal("1"), market_beta=Decimal("1"),
        correlation_concentration=Decimal("0.3"), liquidity_concentration=Decimal("70"),
        volatility_concentration=Decimal("5"), drawdown_budget_used=Decimal("1000"),
        daily_loss_budget_used=Decimal("0"), open_risk=Decimal("500"),
        pending_order_risk=Decimal("0"), version=1,
    )


def timeit(label, fn, n):
    start = time.perf_counter()
    for _ in range(n):
        fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {n} iterations in {elapsed:.3f}s, {elapsed/n*1000:.3f} ms/op")
    return elapsed


def main():
    alloc = CapitalAllocationEngine()
    risk = PortfolioRiskEngine(PortfolioRiskBudget())
    assessor = LiquidityAssessor()
    planner = ExecutionPlanner()
    ctx = make_ctx()
    state = make_state()

    print("PERFORMANCE_SMOKE")
    timeit(
        "capital_allocate",
        lambda: alloc.allocate("a", "d", "BTCUSDT", Decimal("0.04"), ctx),
        2000,
    )
    timeit("portfolio_risk", lambda: risk.evaluate_new_risk(
        state=state, symbol="SOLUSDT", cluster="HIGH_BETA_ALT",
        requested_exposure_delta=Decimal("500"), direction="LONG"), 2000)
    assessment = assessor.assess(symbol="BTCUSDT", spread_bps=Decimal("2"),
                                 depth=Decimal("100000"), volume_24h=Decimal("1000000"),
                                 size=Decimal("500"), freshness_seconds=0.5)
    timeit("liquidity_assess", lambda: assessor.assess(
        symbol="BTCUSDT", spread_bps=Decimal("2"), depth=Decimal("100000"),
        volume_24h=Decimal("1000000"), size=Decimal("500"), freshness_seconds=0.5), 2000)
    timeit("execution_plan", lambda: planner.plan(
        assessment=assessment, order_size=Decimal("500"), spread_bps=Decimal("2"),
        urgent=False, thesis_invalidated=False), 2000)
    print("PERFORMANCE_SMOKE_DONE")


if __name__ == "__main__":
    main()
