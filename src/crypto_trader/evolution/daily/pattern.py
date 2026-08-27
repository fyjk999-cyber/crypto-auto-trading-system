"""PatternCandidate extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PatternCandidate:
    pattern_id: str
    scope: str
    pattern_type: str
    conditions: list
    evidence_count: int
    decision_ids: list
    confidence: float
    status: str = "CANDIDATE"

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "scope": self.scope,
            "pattern_type": self.pattern_type,
            "conditions": list(self.conditions),
            "evidence_count": self.evidence_count,
            "decision_ids": list(self.decision_ids),
            "confidence": self.confidence,
            "status": self.status,
        }


def extract_patterns(error_events: list) -> list[PatternCandidate]:
    counts: dict[str, list[str]] = {}
    for event in error_events:
        counts.setdefault(event.category, []).append(event.decision_id)
    patterns = []
    for category, decision_ids in counts.items():
        if len(decision_ids) >= 2:
            patterns.append(
                PatternCandidate(
                    pattern_id=f"pat_{category.lower()}",
                    scope="GLOBAL",
                    pattern_type=category,
                    conditions=[category],
                    evidence_count=len(decision_ids),
                    decision_ids=decision_ids,
                    confidence=min(0.9, 0.5 + len(decision_ids) * 0.1),
                )
            )
    return patterns
