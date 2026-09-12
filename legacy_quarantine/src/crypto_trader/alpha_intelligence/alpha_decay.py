"""Alpha decay detection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class DecayResult:
    degraded: bool
    weight_multiplier: Decimal
    reason: str


class AlphaDecayDetector:
    def detect(
        self,
        *,
        recent_sharpe: Decimal,
        baseline_sharpe: Decimal,
        recent_drawdown_pct: Decimal,
        win_rate_change: Decimal,
    ) -> DecayResult:
        reasons = []
        multiplier = D("1")
        if recent_sharpe < baseline_sharpe * D("0.5"):
            multiplier *= D("0.5")
            reasons.append("SHARPE_DECAY")
        if recent_drawdown_pct > D("15"):
            multiplier *= D("0.6")
            reasons.append("DRAWDOWN")
        if win_rate_change < D("-0.1"):
            multiplier *= D("0.8")
            reasons.append("WIN_RATE_DROP")
        return DecayResult(
            degraded=multiplier < D("0.9"),
            weight_multiplier=max(multiplier, D("0.1")),
            reason=",".join(reasons) or "OK",
        )
