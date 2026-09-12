"""Market regime forecasting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegimeForecast:
    current_regime: str
    future_probability: dict[str, float]


class RegimeForecastEngine:
    def forecast(
        self,
        *,
        current_regime: str,
        trend_strength: float,
        volume_trend: float,
        funding_extreme: float,
    ) -> RegimeForecast:
        if current_regime == "TREND_BULL":
            cont = min(0.9, 0.55 + trend_strength * 0.3)
            rev = 0.15 if funding_extreme > 0.5 else 0.10
        else:
            cont = 0.4 + trend_strength * 0.2
            rev = 0.3
        cont = max(0.0, min(1.0, cont))
        rev = max(0.0, min(1.0, rev))
        rng = max(0.0, 1.0 - cont - rev)
        return RegimeForecast(
            current_regime=current_regime,
            future_probability={
                "trend_continue": round(cont, 3),
                "range": round(rng, 3),
                "reversal": round(rev, 3),
            },
        )
