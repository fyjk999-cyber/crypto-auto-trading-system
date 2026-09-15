"""AI Long/Short decision engine. No direct execution.

Low-Risk V2 Phase 3: this layer is a RECOMMENDATION consumer. ``decide()``
keeps its historical signature/behavior for existing callers; the new
``recommend_from_evidence()`` builds an auditable recommendation from the
25-model expert evidence package. Neither method can place an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_trader.ai_decision.conflict import resolve_conflict
from crypto_trader.ai_decision.fusion import fuse
from crypto_trader.ai_decision.recommendation import (
    RecommendationEngine,
    TradingRecommendation,
)


@dataclass
class DirectionDecision:
    symbol: str
    decision: str
    confidence: float
    quant_score: float
    ai_score: float
    final_score: float
    # Additive Low-Risk V2 field: recommendation-only context (never authority).
    recommendation: dict[str, Any] | None = None
    authority: str = "RECOMMENDATION_ONLY"


class AIDecisionEngine:
    def __init__(self, recommendation_engine: RecommendationEngine | None = None) -> None:
        self.recommendation_engine = recommendation_engine or RecommendationEngine()

    def recommend_from_evidence(self, package: dict[str, Any]) -> TradingRecommendation:
        """Build a recommendation from the 25-model package. Never executes."""
        return self.recommendation_engine.build(package)

    def decide_from_evidence(self, package: dict[str, Any]) -> DirectionDecision:
        """Recommendation view compatible with the historical direction shape."""
        recommendation = self.recommend_from_evidence(package)
        return DirectionDecision(
            symbol=recommendation.symbol,
            decision=(
                "NO_TRADE"
                if recommendation.suggested_direction == "NEUTRAL"
                else recommendation.suggested_direction
            ),
            confidence=recommendation.confidence,
            quant_score=recommendation.raw_consensus_score,
            ai_score=recommendation.correlation_adjusted_score,
            final_score=recommendation.score,
            recommendation=recommendation.as_dict(),
        )

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
