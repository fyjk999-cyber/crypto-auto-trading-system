"""Learning models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MistakeRecord:
    mistake_type: str
    symbol: str
    description: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "mistake_type": self.mistake_type,
            "symbol": self.symbol,
            "description": self.description,
            "timestamp": self.timestamp,
        }


@dataclass
class LessonRecord:
    lesson: str
    symbol: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {"lesson": self.lesson, "symbol": self.symbol, "timestamp": self.timestamp}
