"""AI Long/Short decision engine. No direct execution."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.ai_decision.conflict import resolve_conflict
from crypto_trader.ai_decision.fusion import fuse


@dataclass
class DirectionDecision:
    symbol: str
    decision: str
    confidence: float
    quant_score: float
    ai_score: float
    final_score: float


class AIDecisionEngine:
    def decide(
        self,
        *,
        symbol: str,
        quant_decision: str,
        quant_confidence: float,
        ai_direction: str,
        ai_confidence: float,
    ) -> DirectionDecision:
        if quant_decision != ai_direction and ai_direction not in ("NEUTRAL",):
            conflict = resolve_conflict(
                quant_decision, ai_direction, quant_confidence, ai_confidence
            )
            decision = conflict.decision
            confidence = conflict.confidence
            fusion = fuse(
                decision if decision != "NO_TRADE" else "NO_TRADE", confidence, "NEUTRAL", 0.0
            )
        else:
            fusion = fuse(quant_decision, quant_confidence, ai_direction, ai_confidence)
            decision = fusion.decision
            confidence = abs(fusion.final_score)
        return DirectionDecision(
            symbol=symbol,
            decision=decision,
            confidence=round(confidence, 3),
            quant_score=fusion.quant_score,
            ai_score=fusion.ai_score,
            final_score=fusion.final_score,
        )
