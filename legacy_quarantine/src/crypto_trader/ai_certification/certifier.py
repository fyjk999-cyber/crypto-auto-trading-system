"""AI trader certification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CertificationResult:
    status: str  # CERTIFIED | NOT_CERTIFIED
    score: int
    reasons: list[str]


class AICertifier:
    def certify(
        self, *, performance_score: float, intelligence_score: float, discipline_score: float
    ) -> CertificationResult:
        score = int(
            (performance_score * 0.4 + intelligence_score * 0.35 + discipline_score * 0.25) * 100
        )
        reasons = []
        if performance_score < 0.6:
            reasons.append("PERFORMANCE_WEAK")
        if intelligence_score < 0.6:
            reasons.append("INTELLIGENCE_WEAK")
        if discipline_score < 0.7:
            reasons.append("DISCIPLINE_WEAK")
        return CertificationResult("CERTIFIED" if not reasons else "NOT_CERTIFIED", score, reasons)
