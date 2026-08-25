"""Factor importance engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class FactorImportance:
    factor: str
    importance: Decimal
    rank: int
    metrics: dict
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "importance": str(self.importance),
            "rank": self.rank,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
        }


class FactorImportanceEngine:
    def compute(self, factors: list[dict]) -> list[FactorImportance]:
        scored = []
        for f in factors:
            historical = D(str(f.get("historical_contribution", "0")))
            stability = D(str(f.get("predictive_stability", "0")))
            regime_coverage = D(str(f.get("regime_coverage", "0")))
            research_confidence = D(str(f.get("research_confidence", "0")))
            decay = D(str(f.get("decay_penalty", "0")))
            importance = (
                historical * D("0.3")
                + stability * D("0.25")
                + regime_coverage * D("0.2")
                + research_confidence * D("0.25")
                - decay
            )
            importance = max(D("0"), min(D("1"), importance))
            scored.append((f.get("factor", "unknown"), importance))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            FactorImportance(
                factor=name,
                importance=value,
                rank=rank,
                metrics={
                    "historical_contribution": "0",
                    "predictive_stability": "0",
                    "regime_coverage": "0",
                    "research_confidence": "0",
                    "decay_penalty": "0",
                },
            )
            for rank, (name, value) in enumerate(scored, start=1)
        ]
