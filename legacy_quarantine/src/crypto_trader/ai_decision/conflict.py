"""Conflict resolver."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConflictResolution:
    decision: str
    confidence: float
    resolved: bool
    reason: str


def resolve_conflict(
    quant_decision: str, ai_direction: str, quant_confidence: float, ai_confidence: float
) -> ConflictResolution:
    if quant_decision in ("NO_TRADE", "NEUTRAL") or ai_direction in ("NO_TRADE", "NEUTRAL"):
        return ConflictResolution("NO_TRADE", 0.0, False, "ONE_SIDE_NEUTRAL")
    if quant_decision == ai_direction:
        return ConflictResolution(
            quant_decision, max(quant_confidence, ai_confidence), True, "AGREEMENT"
        )
    if ai_confidence > 0.85:
        return ConflictResolution("NO_TRADE", 0.0, False, "AI_CONFLICT_HIGH_CONFIDENCE")
    return ConflictResolution(quant_decision, quant_confidence * 0.5, True, "QUANT_WINS_LOW_AI")
