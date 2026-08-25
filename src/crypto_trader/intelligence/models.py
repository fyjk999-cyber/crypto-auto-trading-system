"""Market intelligence models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MarketIntelligenceContext:
    symbol: str
    market_regime: dict
    factor_summary: dict
    factor_confidence: dict
    positive_evidence: list[str]
    negative_evidence: list[str]
    research_summary: dict
    historical_similarity: dict
    overall_confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "market_regime": self.market_regime,
            "factor_summary": self.factor_summary,
            "factor_confidence": self.factor_confidence,
            "positive_evidence": self.positive_evidence,
            "negative_evidence": self.negative_evidence,
            "research_summary": self.research_summary,
            "historical_similarity": self.historical_similarity,
            "overall_confidence": self.overall_confidence,
            "timestamp": self.timestamp,
        }
