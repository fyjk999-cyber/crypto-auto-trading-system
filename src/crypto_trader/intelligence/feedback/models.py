"""Research feedback models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ResearchFeedback:
    symbol: str
    market_state: str
    validated_factors: list[str]
    factor_confidence: dict
    research_consensus: dict
    historical_context: dict
    risk_notes: list[str]
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "market_state": self.market_state,
            "validated_factors": self.validated_factors,
            "factor_confidence": self.factor_confidence,
            "research_consensus": self.research_consensus,
            "historical_context": self.historical_context,
            "risk_notes": self.risk_notes,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class FeedbackValidation:
    feedback_id: str
    status: str
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "feedback_id": self.feedback_id,
            "status": self.status,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
