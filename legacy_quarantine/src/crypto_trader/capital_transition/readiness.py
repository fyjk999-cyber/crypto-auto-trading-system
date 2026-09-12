"""Demo-to-capital readiness. Never enables LIVE automatically."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ReadinessResult:
    ready: bool
    reasons: list[str]


class CapitalReadiness:
    def evaluate(
        self,
        *,
        shadow_days: int,
        demo_days: int,
        expectancy: Decimal,
        profit_factor: Decimal,
        sharpe: Decimal,
        max_dd_pct: Decimal,
        risk_violations: int,
        uptime_pct: Decimal,
    ) -> ReadinessResult:
        reasons = []
        if shadow_days < 30:
            reasons.append("SHADOW_DAYS<30")
        if demo_days < 30:
            reasons.append("DEMO_DAYS<30")
        if expectancy <= 0:
            reasons.append("EXPECTANCY_NOT_POSITIVE")
        if profit_factor <= Decimal("1.3"):
            reasons.append("PROFIT_FACTOR<=1.3")
        if sharpe <= Decimal("1"):
            reasons.append("SHARPE<=1")
        if max_dd_pct >= Decimal("20"):
            reasons.append("MAX_DD>=20%")
        if risk_violations > 0:
            reasons.append("RISK_VIOLATIONS")
        if uptime_pct < Decimal("99"):
            reasons.append("UPTIME<99%")
        return ReadinessResult(ready=not reasons, reasons=reasons)
