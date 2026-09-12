"""Capital allocation engine.

Converts a trading thesis into a bounded capital recommendation.
This is an advisory layer; RiskEngine remains final authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class CapitalAllocationContext:
    account_equity: Decimal
    available_equity: Decimal
    current_cash: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    symbol_exposure: Decimal
    coin_cluster_exposure: Decimal
    strategy_exposure: Decimal
    conviction_score: Decimal
    calibrated_confidence: Decimal
    strategy_quality: Decimal
    strategy_lifecycle_state: str
    alpha_decay_state: str
    market_regime: str
    regime_forecast: str
    coin_behavior_profile: str
    liquidity_score: Decimal
    estimated_slippage: Decimal
    volatility: Decimal
    drawdown_state: Decimal
    daily_loss_state: Decimal
    portfolio_risk_budget: Decimal
    correlation_risk: Decimal
    transaction_cost_estimate: Decimal


@dataclass
class CapitalAllocationDecision:
    allocation_id: str
    decision_id: str
    symbol: str
    requested_capital_fraction: Decimal
    recommended_capital_fraction: Decimal
    recommended_notional: Decimal
    recommended_risk_budget: Decimal
    max_allowed_fraction_before_risk_engine: Decimal
    allocation_confidence: Decimal
    reason_codes: list[str] = field(default_factory=list)
    policy_version: str = "1.0"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class CapitalAllocationEngine:
    BASE_FRACTION = D("0.02")
    HARD_MAX_FRACTION = D("0.05")

    def allocate(
        self,
        allocation_id: str,
        decision_id: str,
        symbol: str,
        requested_fraction: Decimal,
        ctx: CapitalAllocationContext,
    ) -> CapitalAllocationDecision:
        fraction = min(D(requested_fraction), self.HARD_MAX_FRACTION)
        reasons: list[str] = []
        confidence = D("1")

        if ctx.liquidity_score < D("50"):
            fraction *= D("0.5")
            reasons.append("LOW_LIQUIDITY")
        if ctx.correlation_risk > D("0.7"):
            fraction *= D("0.6")
            reasons.append("HIGH_CORRELATION")
        if ctx.coin_cluster_exposure > D("0.15"):
            fraction *= D("0.7")
            reasons.append("CLUSTER_CONCENTRATION")
        if ctx.volatility > D("8"):
            fraction *= D("0.7")
            reasons.append("HIGH_VOLATILITY")
        if ctx.drawdown_state > D("0.1"):
            fraction *= D("0.5")
            reasons.append("PORTFOLIO_DRAWDOWN")
        if ctx.daily_loss_state > D("0.01"):
            fraction *= D("0.6")
            reasons.append("DAILY_LOSS_STATE")
        if ctx.strategy_lifecycle_state in ("DEGRADING", "RETIRED"):
            fraction *= D("0.3")
            reasons.append("STRATEGY_DEGRADED")
        if ctx.alpha_decay_state == "DECAYED":
            fraction *= D("0.5")
            reasons.append("ALPHA_DECAY")
        if ctx.calibrated_confidence < D("0.5"):
            fraction *= D("0.5")
            reasons.append("POOR_CALIBRATION")
        if ctx.strategy_quality < D("0.4"):
            fraction *= D("0.5")
            reasons.append("WEAK_STRATEGY_QUALITY")
        if ctx.transaction_cost_estimate > D("0.003"):
            fraction *= D("0.6")
            reasons.append("HIGH_TRANSACTION_COST")
        if ctx.regime_forecast in ("REVERSAL", "UNCERTAIN"):
            fraction *= D("0.7")
            reasons.append("REGIME_UNCERTAINTY")

        conviction_cap = (
            self.BASE_FRACTION * (D("1") + ctx.conviction_score) * ctx.calibrated_confidence
        )
        fraction = min(fraction, conviction_cap)
        fraction = max(D("0"), min(fraction, self.HARD_MAX_FRACTION))
        notional = ctx.account_equity * fraction
        risk_budget = notional * D("0.02")
        confidence = confidence * max(D("0.1"), ctx.calibrated_confidence)
        return CapitalAllocationDecision(
            allocation_id=allocation_id,
            decision_id=decision_id,
            symbol=symbol,
            requested_capital_fraction=D(requested_fraction),
            recommended_capital_fraction=fraction,
            recommended_notional=notional,
            recommended_risk_budget=risk_budget,
            max_allowed_fraction_before_risk_engine=self.HARD_MAX_FRACTION,
            allocation_confidence=confidence,
            reason_codes=reasons,
        )
