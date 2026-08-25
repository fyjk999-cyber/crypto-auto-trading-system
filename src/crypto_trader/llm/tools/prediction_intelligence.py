"""Prediction intelligence LLM tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.intelligence.prediction.confidence_forecast import ConfidenceForecastEngine
from crypto_trader.intelligence.prediction.factor_forecast import FactorForecastEngine
from crypto_trader.intelligence.prediction.regime_forecast import RegimeForecastEngine


@dataclass
class PredictionToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class PredictionIntelligenceTools:
    def __init__(self) -> None:
        self.regime_engine = RegimeForecastEngine()
        self.factor_engine = FactorForecastEngine()
        self.confidence_engine = ConfidenceForecastEngine()

    async def get_regime_forecast(
        self, symbol: str, current_regime: str, trend_strength: float, volatility: float
    ) -> PredictionToolResult:
        result = self.regime_engine.forecast(
            symbol=symbol,
            current_regime=current_regime,
            trend_strength=trend_strength,
            volatility=volatility,
        )
        return PredictionToolResult(True, result.to_dict(), None)

    async def get_factor_forecast(
        self, factor: str, current_health: str, decay_score: float, regime_match: float
    ) -> PredictionToolResult:
        result = self.factor_engine.forecast(
            factor=factor,
            current_health=current_health,
            decay_score=decay_score,
            regime_match=regime_match,
        )
        return PredictionToolResult(True, result.to_dict(), None)

    async def get_research_confidence_forecast(
        self, research_id: str, knowledge_health: str, age_days: float
    ) -> PredictionToolResult:
        result = self.confidence_engine.forecast(
            research_id=research_id, knowledge_health=knowledge_health, age_days=age_days
        )
        return PredictionToolResult(True, result.to_dict(), None)
