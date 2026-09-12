"""Quant + AI fusion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FusionScore:
    quant_score: float
    ai_score: float
    final_score: float
    decision: str


def fuse(
    quant_decision: str, quant_confidence: float, ai_direction: str, ai_confidence: float
) -> FusionScore:
    quant_map = {"LONG": 1.0, "SHORT": -1.0, "NO_TRADE": 0.0}
    ai_map = {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}
    quant_score = quant_map.get(quant_decision, 0.0) * quant_confidence
    ai_score = ai_map.get(ai_direction, 0.0) * ai_confidence
    final = quant_score * 0.6 + ai_score * 0.4
    decision = "LONG" if final > 0.15 else "SHORT" if final < -0.15 else "NO_TRADE"
    return FusionScore(
        quant_score=round(quant_score, 3),
        ai_score=round(ai_score, 3),
        final_score=round(final, 3),
        decision=decision,
    )
