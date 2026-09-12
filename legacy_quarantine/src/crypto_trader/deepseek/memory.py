"""AI experience memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AIExperienceRecord:
    symbol: str
    market_state: dict
    ai_prediction: str
    confidence: float
    quant_signal: str
    final_decision: str
    trade_result: str | None = None
    pnl: float = 0.0
    cost_breakdown: dict = field(default_factory=dict)
    mistake: str = ""
    lesson: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AIExperienceMemory:
    def __init__(self) -> None:
        self.records: list[AIExperienceRecord] = []

    def store(self, record: AIExperienceRecord) -> None:
        self.records.append(record)

    def all(self) -> list[AIExperienceRecord]:
        return list(self.records)

    def count(self) -> int:
        return len(self.records)
