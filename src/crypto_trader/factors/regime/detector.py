"""Data-driven market regime detector. No LLM involved."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.regime.models import MarketRegime


class MarketRegimeDetector:
    def detect(
        self,
        symbol: str,
        *,
        trend_strength: Decimal,
        volatility: Decimal,
        volume_change: Decimal,
        oi_change: Decimal,
        funding: Decimal,
        price_change: Decimal,
    ) -> MarketRegime:
        evidence = []
        confidence = 0.5
        regime = "RANGING"
        if abs(price_change) > 5:
            regime = "PANIC"
            confidence = 0.8
            evidence.append("extreme price move")
        elif volatility > 0.7:
            regime = "HIGH_VOLATILITY"
            confidence = 0.7
            evidence.append("volatility high")
        elif volatility < 0.25:
            regime = "LOW_VOLATILITY"
            confidence = 0.7
            evidence.append("volatility low")
        elif abs(trend_strength) > 0.4:
            regime = "TRENDING"
            confidence = 0.8
            evidence.append("trend strength significant")
            if trend_strength > 0:
                evidence.append("uptrend")
            else:
                evidence.append("downtrend")
        elif oi_change > 0.1 and volume_change > 0:
            regime = "ACCUMULATION"
            confidence = 0.6
            evidence.append("OI rising with volume")
        elif oi_change < -0.1 and volume_change < 0:
            regime = "DISTRIBUTION"
            confidence = 0.6
            evidence.append("OI falling with volume drop")
        else:
            regime = "RANGING"
            confidence = 0.55
            evidence.append("no dominant regime")
        if funding > 0.0005:
            evidence.append("funding crowded long")
        elif funding < -0.0005:
            evidence.append("funding crowded short")
        return MarketRegime(symbol=symbol, regime=regime, confidence=confidence, evidence=evidence)
