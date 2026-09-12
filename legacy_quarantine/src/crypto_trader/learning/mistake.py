"""Mistake learning."""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_trader.learning.models import MistakeRecord


@dataclass
class MistakeLog:
    records: list[MistakeRecord] = field(default_factory=list)

    def add(self, mistake_type: str, symbol: str, description: str) -> MistakeRecord:
        record = MistakeRecord(mistake_type, symbol, description)
        self.records.append(record)
        return record

    def frequent(self, top_k: int = 5) -> list[str]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.mistake_type] = counts.get(record.mistake_type, 0) + 1
        return sorted(counts, key=counts.get, reverse=True)[:top_k]
