"""AI prediction memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AIPredictionRecord:
    prediction_id: str
    symbol: str
    direction: str
    confidence: float
    actual_result: float | None = None
    error_category: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AIPredictionMemory:
    def __init__(self) -> None:
        self.records: dict[str, AIPredictionRecord] = {}

    def store(self, record: AIPredictionRecord) -> None:
        self.records[record.prediction_id] = record

    def get(self, prediction_id: str) -> AIPredictionRecord | None:
        return self.records.get(prediction_id)

    def all(self) -> list[AIPredictionRecord]:
        return list(self.records.values())
