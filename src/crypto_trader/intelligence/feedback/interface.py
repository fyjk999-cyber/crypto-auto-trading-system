"""Research feedback interface."""

from __future__ import annotations

from crypto_trader.intelligence.feedback.builder import ResearchFeedbackBuilder
from crypto_trader.intelligence.feedback.validator import FeedbackValidator


class ResearchFeedbackInterface:
    def __init__(self) -> None:
        self.builder = ResearchFeedbackBuilder()
        self.validator = FeedbackValidator()
        self.latest: dict[str, dict] = {}

    def build_and_validate(
        self,
        *,
        symbol: str,
        market_intelligence: dict,
        factor_confidences: dict,
        research_consensus: dict,
        historical_context: dict,
        knowledge_health: dict,
    ) -> dict:
        feedback = self.builder.build(
            symbol=symbol,
            market_intelligence=market_intelligence,
            factor_confidences=factor_confidences,
            research_consensus=research_consensus,
            historical_context=historical_context,
            knowledge_health=knowledge_health,
        )
        feedback_id = f"{symbol}:{feedback.timestamp}"
        validation = self.validator.validate(feedback_id=feedback_id, feedback=feedback.to_dict())
        if validation.status == "PASS":
            self.latest[symbol] = feedback.to_dict()
            return feedback.to_dict()
        return {"symbol": symbol, "status": "REJECTED", "reason": validation.reason}

    def get(self, symbol: str) -> dict | None:
        return self.latest.get(symbol)
