"""Capital readiness evaluation (multi-dimensional, no LIVE_READY output)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class CapitalReadinessAssessment:
    status: str  # INSUFFICIENT_DATA | NOT_READY | CONDITIONAL | READY_FOR_MICRO_CAPITAL_REVIEW
    reasons: list[str] = field(default_factory=list)


class CapitalReadinessEvaluator:
    def evaluate(
        self,
        *,
        shadow_days: float,
        valid_observation_days: int,
        shadow_trade_count: int,
        profit_factor: Decimal,
        sharpe: Decimal,
        max_drawdown_pct: Decimal,
        calibration_error: Decimal,
        operational_uptime: Decimal,
        risk_violations: int,
        unresolved_incidents: int,
        data_quality: float,
    ) -> CapitalReadinessAssessment:
        reasons = []
        if shadow_days < 90:
            reasons.append("SHADOW_DURATION<90")
        if valid_observation_days < 70:
            reasons.append("VALID_OBSERVATION_DAYS<70")
        if shadow_trade_count < 100:
            reasons.append("TRADE_COUNT<100")
        if profit_factor < Decimal("1.3"):
            reasons.append("PF<1.3")
        if sharpe < Decimal("1"):
            reasons.append("SHARPE<1")
        if max_drawdown_pct >= Decimal("20"):
            reasons.append("MAX_DD>=20%")
        if calibration_error > Decimal("0.2"):
            reasons.append("CALIBRATION_ERROR")
        if operational_uptime < Decimal("99"):
            reasons.append("UPTIME<99%")
        if risk_violations > 0:
            reasons.append("RISK_VIOLATIONS")
        if unresolved_incidents > 0:
            reasons.append("UNRESOLVED_INCIDENTS")
        if data_quality < 80:
            reasons.append("DATA_QUALITY_LOW")

        if shadow_days < 90 or valid_observation_days < 70:
            return CapitalReadinessAssessment("INSUFFICIENT_DATA", reasons)
        if reasons:
            return CapitalReadinessAssessment("NOT_READY", reasons)
        if shadow_trade_count < 200:
            return CapitalReadinessAssessment("CONDITIONAL", ["TRADE_COUNT_BELOW_200"])
        return CapitalReadinessAssessment("READY_FOR_MICRO_CAPITAL_REVIEW", [])
