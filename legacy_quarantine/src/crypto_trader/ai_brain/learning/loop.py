"""Learning loop: reuses existing memory, no new memory system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LearningLoop:
    lessons: list[dict] = field(default_factory=list)

    def learn(
        self, *, symbol: str, result: str, mistakes: list[str] | None = None, lesson: str = ""
    ) -> dict:
        record = {
            "symbol": symbol,
            "result": result,
            "mistakes": mistakes or [],
            "lesson": lesson,
            "type": "trade_learning",
        }
        self.lessons.append(record)
        return record
