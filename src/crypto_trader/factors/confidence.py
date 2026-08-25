"""Factor confidence engine: current trustworthiness of a factor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class FactorConfidence:
    factor: str
    current_value: Decimal
    historical_reliability: Decimal
    regime_match: Decimal
    decay_penalty: Decimal
    confidence: Decimal
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "current_value": str(self.current_value),
            "historical_reliability": str(self.historical_reliability),
            "regime_match": str(self.regime_match),
            "decay_penalty": str(self.decay_penalty),
            "confidence": str(self.confidence),
            "timestamp": self.timestamp,
        }


class FactorConfidenceEngine:
    def compute(
        self,
        *,
        factor: str,
        current_value: Decimal,
        historical_reliability: Decimal,
        regime_match: Decimal,
        decay_status: str = "HEALTHY",
    ) -> FactorConfidence:
        penalty = D("0.1") if decay_status == "DEGRADING" else D("0")
        confidence = (
            D(current_value).copy_abs() * D("0.2")
            + D(historical_reliability) * D("0.5")
            + D(regime_match) * D("0.3")
            - penalty
        )
        confidence = max(D("0"), min(D("1"), confidence))
        return FactorConfidence(
            factor,
            D(current_value),
            D(historical_reliability),
            D(regime_match),
            penalty,
            confidence,
        )
