"""Live readiness checker. Never enables LIVE automatically."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ReadinessResult:
    status: str  # READY | NOT_READY
    reasons: list[str]


class LiveReadinessChecker:
    def evaluate(
        self,
        *,
        shadow_days: int,
        demo_days: int,
        profit_factor: Decimal,
        sharpe: Decimal,
        max_dd_pct: Decimal,
        uptime_pct: Decimal,
        risk_violations: int,
    ) -> ReadinessResult:
        reasons = []
        if shadow_days < 30:
            reasons.append("SHADOW_DAYS<30")
        if demo_days < 30:
            reasons.append("DEMO_DAYS<30")
        if profit_factor <= Decimal("1.3"):
            reasons.append("PROFIT_FACTOR<=1.3")
        if sharpe <= Decimal("1"):
            reasons.append("SHARPE<=1")
        if max_dd_pct >= Decimal("20"):
            reasons.append("MAX_DD>=20%")
        if uptime_pct < Decimal("99"):
            reasons.append("UPTIME<99%")
        if risk_violations > 0:
            reasons.append("RISK_VIOLATIONS")
        return ReadinessResult("READY" if not reasons else "NOT_READY", reasons)
