"""Knowledge evolution engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class KnowledgeEvolutionStatus:
    knowledge_id: str
    status: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "knowledge_id": self.knowledge_id,
            "status": self.status,
            "timestamp": self.timestamp,
        }


class KnowledgeEvolutionEngine:
    def evaluate(self, *, knowledge_id: str, decay_score: float) -> KnowledgeEvolutionStatus:
        if decay_score >= 0.7:
            status = "INVALID"
        elif decay_score >= 0.45:
            status = "DEGRADED"
        elif decay_score >= 0.25:
            status = "AGING"
        else:
            status = "VALID"
        return KnowledgeEvolutionStatus(knowledge_id=knowledge_id, status=status)
