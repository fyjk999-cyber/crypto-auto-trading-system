"""Research priority engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ResearchPriority:
    research_id: str
    priority: float
    level: str
    score: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "research_id": self.research_id,
            "priority": self.priority,
            "level": self.level,
            "score": self.score,
            "timestamp": self.timestamp,
        }


class ResearchPriorityEngine:
    def evaluate(
        self,
        *,
        research_id: str,
        market_relevance: float,
        anomaly_severity: float,
        novelty: float,
        confidence: float,
        potential_impact: float,
    ) -> ResearchPriority:
        score = (
            0.3 * market_relevance
            + 0.2 * anomaly_severity
            + 0.15 * novelty
            + 0.15 * confidence
            + 0.2 * potential_impact
        )
        level = "HIGH" if score >= 0.7 else "MEDIUM" if score >= 0.45 else "LOW"
        return ResearchPriority(
            research_id=research_id, priority=round(score, 3), level=level, score=round(score, 3)
        )

    def rank(self, items: list[ResearchPriority]) -> list[ResearchPriority]:
        return sorted(items, key=lambda p: p.priority, reverse=True)
