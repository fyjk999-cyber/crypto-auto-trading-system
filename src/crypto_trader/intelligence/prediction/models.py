"""Prediction models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RegimeForecast:
    symbol: str
    current_regime: str
    probabilities: dict[str, float]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "current_regime": self.current_regime,
            "probabilities": self.probabilities,
            "timestamp": self.timestamp,
        }


@dataclass
class FactorForecast:
    factor: str
    current_health: str
    degrading_probability: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "current_health": self.current_health,
            "degrading_probability": self.degrading_probability,
            "timestamp": self.timestamp,
        }


@dataclass
class ConfidenceForecast:
    research_id: str
    valid_probability: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "research_id": self.research_id,
            "valid_probability": self.valid_probability,
            "timestamp": self.timestamp,
        }
