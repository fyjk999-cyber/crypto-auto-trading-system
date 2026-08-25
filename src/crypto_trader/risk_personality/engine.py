"""AI risk personality (advisory only)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class RiskPersonality:
    style: str
    risk_preference: str
    leverage_preference: Decimal
    holding_period_preference: str
    trade_frequency: str
    confidence_threshold: Decimal


class RiskPersonalityEngine:
    def evaluate(
        self, *, avg_win_rate: Decimal, avg_leverage: Decimal, holding_hours: Decimal
    ) -> RiskPersonality:
        if avg_win_rate > Decimal("0.6") and avg_leverage <= Decimal("2"):
            style = "CONSERVATIVE"
            freq = "LOW"
            threshold = Decimal("0.7")
        elif avg_win_rate > Decimal("0.45"):
            style = "BALANCED"
            freq = "MEDIUM"
            threshold = Decimal("0.6")
        else:
            style = "AGGRESSIVE"
            freq = "HIGH"
            threshold = Decimal("0.5")
        return RiskPersonality(
            style=style,
            risk_preference=style.lower(),
            leverage_preference=avg_leverage,
            holding_period_preference=f"{holding_hours}h",
            trade_frequency=freq,
            confidence_threshold=threshold,
        )
