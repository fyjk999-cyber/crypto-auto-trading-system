"""Factor reliability forecast."""

from __future__ import annotations

from crypto_trader.intelligence.prediction.models import FactorForecast


class FactorForecastEngine:
    def forecast(
        self, *, factor: str, current_health: str, decay_score: float, regime_match: float
    ) -> FactorForecast:
        if current_health in ("DEGRADING", "WARNING"):
            prob = 0.7 + decay_score * 0.3
        else:
            prob = 0.2 + decay_score * 0.3 + (1 - regime_match) * 0.2
        return FactorForecast(
            factor=factor,
            current_health=current_health,
            degrading_probability=round(min(0.95, max(0.05, prob)), 3),
        )
