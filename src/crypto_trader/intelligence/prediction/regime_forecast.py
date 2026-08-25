"""Regime forecast (probability only, not price)."""

from __future__ import annotations

from crypto_trader.intelligence.prediction.models import RegimeForecast


class RegimeForecastEngine:
    def forecast(
        self, *, symbol: str, current_regime: str, trend_strength: float, volatility: float
    ) -> RegimeForecast:
        if current_regime == "TRENDING":
            cont = min(0.9, 0.55 + trend_strength * 0.3)
            high_vol = min(0.3, volatility * 0.5)
        elif current_regime == "RANGING":
            cont = 0.4
            high_vol = min(0.3, volatility * 0.5)
        else:
            cont = 0.3
            high_vol = min(0.6, volatility * 0.7)
        cont = max(0.0, min(1.0, cont))
        high_vol = max(0.0, min(1.0, high_vol))
        ranging = max(0.0, 1.0 - cont - high_vol)
        return RegimeForecast(
            symbol=symbol,
            current_regime=current_regime,
            probabilities={
                "trend_continue": round(cont, 3),
                "range": round(ranging, 3),
                "high_vol": round(high_vol, 3),
            },
        )
