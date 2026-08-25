"""Pattern learning: reuses existing memory, no new memory system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatternMemory:
    patterns: list[dict] = field(default_factory=list)

    def save(self, *, market_pattern: str, decision: str, result: str, lesson: str = "") -> dict:
        record = {
            "market_pattern": market_pattern,
            "decision": decision,
            "result": result,
            "lesson": lesson,
            "type": "pattern_learning",
        }
        self.patterns.append(record)
        return record

    def find(self, market_pattern: str) -> list[dict]:
        return [p for p in self.patterns if p["market_pattern"] == market_pattern]
