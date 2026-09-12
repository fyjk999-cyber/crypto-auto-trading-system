"""Portfolio risk budget engine: fund-level risk, hidden concentration."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class PortfolioRiskState:
    account_equity: Decimal
    cash: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    long_exposure: Decimal
    short_exposure: Decimal
    leveraged_exposure: Decimal
    symbol_exposure: dict
    strategy_exposure: dict
    behavior_cluster_exposure: dict
    btc_beta: Decimal
    market_beta: Decimal
    correlation_concentration: Decimal
    liquidity_concentration: Decimal
    volatility_concentration: Decimal
    drawdown_budget_used: Decimal
    daily_loss_budget_used: Decimal
    open_risk: Decimal
    pending_order_risk: Decimal
    version: int = 1

    def gross_net_correct(self) -> bool:
        return self.gross_exposure >= abs(self.net_exposure)


@dataclass
class PortfolioRiskBudget:
    total_budget_pct: Decimal = Decimal("0.05")
    max_cluster_budget_pct: Decimal = Decimal("0.02")
    max_single_symbol_pct: Decimal = Decimal("0.02")


@dataclass
class PortfolioRiskDecision:
    decision: str  # APPROVE | REDUCE | REJECT
    approved_risk_budget: Decimal
    approved_exposure_delta: Decimal
    reason_codes: list[str] = field(default_factory=list)
    risk_state_version: int = 1


class PortfolioRiskEngine:
    def __init__(self, budget: PortfolioRiskBudget | None = None) -> None:
        self.budget = budget or PortfolioRiskBudget()

    def evaluate_new_risk(
        self,
        *,
        state: PortfolioRiskState,
        symbol: str,
        cluster: str,
        requested_exposure_delta: Decimal,
        direction: str,
    ) -> PortfolioRiskDecision:
        reasons: list[str] = []
        delta = D(requested_exposure_delta)
        equity = D(state.account_equity) if D(state.account_equity) > 0 else D("1")

        cluster_existing = D(str(state.behavior_cluster_exposure.get(cluster, "0")))
        if cluster_existing + abs(delta) > self.budget.max_cluster_budget_pct * equity:
            reasons.append("CLUSTER_CONCENTRATION")

        if state.correlation_concentration > D("0.8"):
            reasons.append("CORRELATION_CONCENTRATION")
        if state.volatility_concentration > D("10"):
            reasons.append("VOLATILITY_CONCENTRATION")
        if state.liquidity_concentration < D("40"):
            reasons.append("LIQUIDITY_CONCENTRATION")

        remaining_budget = max(
            D("0"),
            self.budget.total_budget_pct * equity
            - (state.drawdown_budget_used + state.open_risk + state.pending_order_risk),
        )
        if delta > 0 and remaining_budget < abs(delta):
            reasons.append("RISK_BUDGET_EXHAUSTED")

        if direction == "SHORT" and (state.short_exposure + abs(delta)) > state.gross_exposure * D(
            "0.6"
        ) + abs(delta):
            reasons.append("SHORT_CONCENTRATION")

        if delta > 0 and (state.drawdown_budget_used / equity > D("0.15")):
            reasons.append("DRAWDOWN_STATE")

        if direction not in ("LONG", "SHORT", "EXIT", "REDUCE"):
            reasons.append("INVALID_DIRECTION")

        if not reasons:
            return PortfolioRiskDecision(
                "APPROVE", min(delta, remaining_budget), delta, [], state.version
            )
        if "RISK_BUDGET_EXHAUSTED" in reasons:
            return PortfolioRiskDecision("REJECT", D("0"), D("0"), reasons, state.version)
        return PortfolioRiskDecision(
            "REDUCE",
            min(delta, remaining_budget) if delta > 0 else delta,
            delta,
            reasons,
            state.version,
        )

    def evaluate_exit(self, state: PortfolioRiskState) -> PortfolioRiskDecision:
        return PortfolioRiskDecision("APPROVE", D("0"), D("0"), ["RISK_REDUCING"], state.version)
