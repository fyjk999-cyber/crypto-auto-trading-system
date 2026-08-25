"""Knowledge decay detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class KnowledgeHealth:
    knowledge_id: str
    status: str  # VALID | AGING | DEGRADED | INVALID
    decay_score: float
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "knowledge_id": self.knowledge_id,
            "status": self.status,
            "decay_score": self.decay_score,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class KnowledgeDecayEngine:
    def evaluate(
        self,
        *,
        knowledge_id: str,
        age_days: float,
        performance_change: float,
        regime_change: float,
        contradiction_frequency: float,
    ) -> KnowledgeHealth:
        decay = 0.0
        reasons = []
        if age_days > 90:
            decay += 0.3
            reasons.append("old")
        if performance_change < -0.15:
            decay += 0.35
            reasons.append("performance decline")
        if regime_change > 0.5:
            decay += 0.2
            reasons.append("regime changed")
        if contradiction_frequency > 0.3:
            decay += 0.25
            reasons.append("frequent contradictions")
        decay = min(1.0, decay)
        if decay >= 0.7:
            status = "INVALID"
        elif decay >= 0.45:
            status = "DEGRADED"
        elif decay >= 0.25:
            status = "AGING"
        else:
            status = "VALID"
        return KnowledgeHealth(knowledge_id, status, round(decay, 3), ",".join(reasons) or "fresh")
