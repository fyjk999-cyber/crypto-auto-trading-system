from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from crypto_trader.domain.money import D


class ReviewDecision(str, Enum):
    PASS = "PASS"
    REDUCE = "REDUCE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"
    WAITING_APPROVAL = "WAITING_APPROVAL"


@dataclass
class StructuredReview:
    decision: ReviewDecision
    risk_score: Decimal
    flags: list[str] = field(default_factory=list)
    recommended_position: Decimal = Decimal("0")
    recommended_leverage: Decimal = Decimal("0")
    required_actions: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    review_version: str = "v1"
    reviewer: str = ""


class RiskReviewer:
    """Checks size, leverage, margin, liquidation distance, exposure, drawdown, liquidity."""

    name = "risk_reviewer"

    def review(
        self,
        *,
        leverage: Decimal,
        position_notional: Decimal,
        nav: Decimal,
        maintenance_margin: Decimal,
        liquidation_distance_pct: Decimal,
        gross_exposure_pct: Decimal,
        drawdown_pct: Decimal,
        market_volatility: Decimal,
        liquidity_score: Decimal,
        funding_rate: Decimal,
        market_data_healthy: bool,
    ) -> StructuredReview:
        flags = []
        score = D("0")
        if not market_data_healthy:
            flags.append("MARKET_DATA_STALE")
            score += D("20")
        if D(leverage) > D("6"):
            flags.append("LEVERAGE_ABOVE_HARD_MAX")
            score += D("40")
        if D(liquidation_distance_pct) < D("0.02"):
            flags.append("LIQUIDATION_TOO_CLOSE")
            score += D("30")
        if D(gross_exposure_pct) > D("150"):
            flags.append("GROSS_EXPOSURE_HIGH")
            score += D("20")
        if D(drawdown_pct) > D("30"):
            flags.append("DRAWDOWN_STRESS")
            score += D("30")
        if D(liquidity_score) < D("0.4"):
            flags.append("LIQUIDITY_DETERIORATED")
            score += D("15")
        if D(funding_rate) > D("0.001"):
            flags.append("FUNDING_CROWDED")
            score += D("10")
        decision = (
            ReviewDecision.PASS
            if score == 0
            else (
                ReviewDecision.ESCALATE
                if score >= 60
                else ReviewDecision.REJECT
                if score >= 40
                else ReviewDecision.REDUCE
            )
        )
        return StructuredReview(
            decision=decision,
            risk_score=score,
            flags=flags,
            recommended_position=Decimal("0"),
            recommended_leverage=Decimal("0"),
            reason_codes=flags,
            reviewer=self.name,
        )


class AdversarialReviewer:
    """Finds reasons NOT to execute. Deterministic structured output."""

    name = "adversarial_reviewer"

    def review(
        self,
        *,
        funding_rate: Decimal,
        oi_spike: Decimal,
        basis: Decimal,
        momentum_divergence: Decimal,
        regime_conflict: bool,
        liquidation_cluster: bool,
        volatility_spike: Decimal,
        liquidity_deterioration: bool,
        spread_widening: bool,
        historical_failure_pattern: bool,
        correlation_concentration: bool,
        stale_data: bool,
        execution_uncertainty: bool,
    ) -> StructuredReview:
        flags = []
        score = D("0")
        if stale_data:
            flags.append("STALE_DATA")
            score += D("30")
        if execution_uncertainty:
            flags.append("EXECUTION_UNCERTAINTY")
            score += D("20")
        if D(funding_rate) > D("0.001"):
            flags.append("FUNDING_CROWDED")
            score += D("15")
        if D(oi_spike) > D("0.15"):
            flags.append("OI_SPIKE")
            score += D("15")
        if abs(D(basis)) > D("0.005"):
            flags.append("BASIS_DISLOCATION")
            score += D("15")
        if D(momentum_divergence) > D("0.1"):
            flags.append("MOMENTUM_DIVERGENCE")
            score += D("15")
        if regime_conflict:
            flags.append("REGIME_CONFLICT")
            score += D("20")
        if liquidation_cluster:
            flags.append("LIQUIDATION_CLUSTER")
            score += D("25")
        if D(volatility_spike) > D("0.5"):
            flags.append("VOLATILITY_SPIKE")
            score += D("20")
        if liquidity_deterioration:
            flags.append("LIQUIDITY_DETERIORATION")
            score += D("15")
        if spread_widening:
            flags.append("SPREAD_WIDENING")
            score += D("10")
        if historical_failure_pattern:
            flags.append("HISTORICAL_FAILURE_PATTERN")
            score += D("30")
        if correlation_concentration:
            flags.append("CORRELATION_CONCENTRATION")
            score += D("15")
        decision = (
            ReviewDecision.PASS
            if score == 0
            else (
                ReviewDecision.REJECT
                if score >= 50
                else ReviewDecision.ESCALATE
                if score >= 30
                else ReviewDecision.REDUCE
            )
        )
        return StructuredReview(
            decision=decision,
            risk_score=score,
            flags=flags,
            recommended_position=Decimal("0"),
            recommended_leverage=Decimal("0"),
            reason_codes=flags,
            reviewer=self.name,
        )


class HumanApprovalGate:
    """L4 gate. Timeout rejects; never auto-approves."""

    def __init__(self, timeout_seconds: int = 300) -> None:
        self.timeout_seconds = timeout_seconds
        self.pending: dict[str, datetime] = {}

    def request(self, decision_id: str, now: datetime | None = None) -> ReviewDecision:
        now = now or datetime.now(UTC)
        self.pending[decision_id] = now
        return ReviewDecision.WAITING_APPROVAL

    def resolve(
        self, decision_id: str, approved: bool, now: datetime | None = None
    ) -> ReviewDecision:
        now = now or datetime.now(UTC)
        requested = self.pending.get(decision_id)
        if requested is None:
            return ReviewDecision.REJECT
        if (now - requested).total_seconds() > self.timeout_seconds:
            del self.pending[decision_id]
            return ReviewDecision.REJECT
        del self.pending[decision_id]
        return ReviewDecision.PASS if approved else ReviewDecision.REJECT
