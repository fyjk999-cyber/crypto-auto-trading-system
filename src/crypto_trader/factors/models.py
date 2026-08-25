"""Factor data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass
class FactorResult:
    factor_name: str
    symbol: str
    timeframe: str
    value: Decimal
    confidence: Decimal
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "value": str(self.value),
            "confidence": str(self.confidence),
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class FactorSnapshot:
    symbol: str
    timeframe: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    factors: dict[str, Decimal] = field(default_factory=dict)
    confidence: dict[str, Decimal] = field(default_factory=dict)
    market_state: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "factors": {k: str(v) for k, v in self.factors.items()},
            "confidence": {k: str(v) for k, v in self.confidence.items()},
            "market_state": self.market_state,
        }
