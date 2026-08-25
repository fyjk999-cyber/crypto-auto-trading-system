"""Market regime intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class RegimeResult:
    regime: str
    confidence: float
    supporting_features: list[str] = field(default_factory=list)
    invalid_features: list[str] = field(default_factory=list)


class RegimeIntelligence:
    def classify(
        self,
        *,
        price_change_pct: Decimal,
        volume_ratio: Decimal,
        volatility_pct: Decimal,
        funding: Decimal | None,
        oi_change_pct: Decimal | None,
        btc_dominance_pct: Decimal,
    ) -> RegimeResult:
        if volatility_pct > 8:
            regime = "HIGH_VOLATILITY"
            confidence = min(0.9, float(volatility_pct) / 20)
            return RegimeResult(regime, confidence, ["VOLATILITY"], ["TREND"])
        if price_change_pct > 2 and volume_ratio > 1.2:
            return RegimeResult("TREND_BULL", 0.8, ["PRICE_UP", "VOLUME"], [])
        if price_change_pct < -2:
            return RegimeResult("TREND_BEAR", 0.8, ["PRICE_DOWN"], [])
        return RegimeResult("RANGE", 0.6, ["PRICE_FLAT"], [])
