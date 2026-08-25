"""Research confidence forecast."""

from __future__ import annotations

from crypto_trader.intelligence.prediction.models import ConfidenceForecast


class ConfidenceForecastEngine:
    def forecast(
        self, *, research_id: str, knowledge_health: str, age_days: float
    ) -> ConfidenceForecast:
        base = {"VALID": 0.9, "AGING": 0.6, "DEGRADED": 0.3, "INVALID": 0.05}.get(
            knowledge_health, 0.5
        )
        age_penalty = min(0.4, age_days / 365)
        return ConfidenceForecast(
            research_id=research_id, valid_probability=round(max(0.0, base - age_penalty), 3)
        )
