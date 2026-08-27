"""Lesson engine. Daily lessons remain CANDIDATE."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.evolution.daily.pattern import PatternCandidate


@dataclass
class Lesson:
    lesson_id: str
    scope: str
    type: str
    canonical_statement: str
    evidence_count: int
    supporting_decisions: list
    contradictions: list
    confidence: float
    status: str = "CANDIDATE"

    def to_dict(self) -> dict:
        return {
            "lesson_id": self.lesson_id,
            "scope": self.scope,
            "type": self.type,
            "canonical_statement": self.canonical_statement,
            "evidence_count": self.evidence_count,
            "supporting_decisions": list(self.supporting_decisions),
            "contradictions": list(self.contradictions),
            "confidence": self.confidence,
            "status": self.status,
        }


class LessonEngine:
    def __init__(self, memory_gateway=None) -> None:
        self.memory_gateway = memory_gateway

    def derive_from_pattern(self, pattern: PatternCandidate) -> Lesson:
        return Lesson(
            lesson_id=f"lesson_{pattern.pattern_id}",
            scope=pattern.scope,
            type=pattern.pattern_type,
            canonical_statement=f"{pattern.pattern_type} repeated in similar conditions",
            evidence_count=pattern.evidence_count,
            supporting_decisions=pattern.decision_ids,
            contradictions=[],
            confidence=pattern.confidence,
        )

    def deduplicate(self, lesson: Lesson) -> Lesson | None:
        if self.memory_gateway is None:
            return lesson
        for existing in self.memory_gateway.lessons:
            if existing.get("canonical_statement") == lesson.canonical_statement:
                existing["contradictions"].extend(lesson.contradictions)
                existing["evidence_count"] += lesson.evidence_count
                return None
        return lesson
