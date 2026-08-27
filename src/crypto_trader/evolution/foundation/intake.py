"""Evolution intake gate: weak evidence cannot create candidates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IntakeDecision:
    status: str
    reason: str


def evaluate_intake(
    *,
    evidence_count: int,
    independent_period_count: int,
    contradiction_count: int,
    confidence: float,
    source_type: str,
) -> IntakeDecision:
    if source_type == "CONFIRMED_LESSON":
        if independent_period_count >= 2 and evidence_count >= 3:
            return IntakeDecision("ELIGIBLE", "confirmed lesson with multi-period evidence")
        return IntakeDecision("INSUFFICIENT_EVIDENCE", "not enough independent periods")
    if contradiction_count > evidence_count:
        return IntakeDecision("REJECTED", "contradictions dominate")
    if evidence_count >= 2 and confidence >= 0.5:
        return IntakeDecision("READY_FOR_HYPOTHESIS", "sufficient evidence")
    return IntakeDecision("RESEARCH_REQUIRED", "more research needed")
