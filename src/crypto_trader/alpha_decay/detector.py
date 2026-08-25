"""Alpha decay detection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class DecayStatus:
    decayed: bool
    weight_multiplier: Decimal
    reason: str


class AlphaDecayDetector:
    def detect(
        self,
        *,
        historical_pf: Decimal,
        recent_pf: Decimal,
        win_rate_change: Decimal,
        drawdown_increase: Decimal,
    ) -> DecayStatus:
        pf_ratio = recent_pf / historical_pf if historical_pf > 0 else Decimal("0")
        multiplier = Decimal("1")
        reasons = []
        if pf_ratio < Decimal("0.6"):
            multiplier *= Decimal("0.5")
            reasons.append("PF_DECAY")
        if win_rate_change < Decimal("-0.1"):
            multiplier *= Decimal("0.7")
            reasons.append("WIN_RATE_DECAY")
        if drawdown_increase > Decimal("10"):
            multiplier *= Decimal("0.6")
            reasons.append("DRAWDOWN_INCREASE")
        return DecayStatus(
            decayed=multiplier < Decimal("0.8"),
            weight_multiplier=max(multiplier, Decimal("0.1")),
            reason=",".join(reasons) or "OK",
        )
