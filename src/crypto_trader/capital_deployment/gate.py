"""Controlled capital deployment gate. NEVER enables LIVE automatically."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class DeploymentResult:
    status: str  # READY | NOT_READY
    reasons: list[str]
    live_enabled: bool = False


class DeploymentGate:
    def evaluate(
        self,
        *,
        certification_score: int,
        shadow_days: int,
        demo_days: int,
        max_drawdown_pct: Decimal,
        profit_factor: Decimal,
        risk_violations: int,
    ) -> DeploymentResult:
        reasons = []
        if certification_score < 80:
            reasons.append("CERTIFICATION_SCORE<80")
        if shadow_days < 90:
            reasons.append("SHADOW_DAYS<90")
        if demo_days < 90:
            reasons.append("DEMO_DAYS<90")
        if max_drawdown_pct > Decimal("20"):
            reasons.append("MAX_DD>20%")
        if profit_factor < Decimal("1.3"):
            reasons.append("PROFIT_FACTOR<1.3")
        if risk_violations > 0:
            reasons.append("RISK_VIOLATIONS")
        return DeploymentResult(
            status="NOT_READY" if reasons else "READY", reasons=reasons, live_enabled=False
        )
