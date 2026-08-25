"""Trade review."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class TradeReview:
    symbol: str
    entry_reason: str
    exit_reason: str
    prediction_accuracy: float
    decision_quality: float
    mistakes: list[str]
    lessons: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_reason": self.entry_reason,
            "exit_reason": self.exit_reason,
            "prediction_accuracy": self.prediction_accuracy,
            "decision_quality": self.decision_quality,
            "mistakes": self.mistakes,
            "lessons": self.lessons,
            "timestamp": self.timestamp,
        }
