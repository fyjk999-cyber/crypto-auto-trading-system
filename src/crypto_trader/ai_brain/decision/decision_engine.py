"""AI Trading Brain decision engine (intent only, no execution)."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import TradingIntent
from crypto_trader.ai_brain.observation.observer import MarketObserver
from crypto_trader.ai_brain.reasoning.challenge import SelfChallenge
from crypto_trader.ai_brain.thesis.builder import ThesisBuilder


class AITradingBrain:
    def __init__(self) -> None:
        self.observer = MarketObserver()
        self.thesis_builder = ThesisBuilder()
        self.challenger = SelfChallenge()

    def analyze(
        self,
        *,
        symbol: str,
        market_state: str,
        factor_intelligence: dict | None = None,
        portfolio: dict | None = None,
        direction: str = "NO_TRADE",
        thesis: str = "",
        supporting: list[str] | None = None,
        contradicting: list[str] | None = None,
        confidence: float = 0.5,
        invalid_conditions: list[str] | None = None,
    ) -> TradingIntent:
        situation = self.observer.observe(
            market_state=market_state, factor_intelligence=factor_intelligence, portfolio=portfolio
        )
        challenge = self.challenger.challenge(
            thesis=thesis,
            supporting=supporting or [],
            contradicting=contradicting or [],
            base_confidence=confidence,
        )
        if not thesis:
            return TradingIntent(
                symbol,
                "NO_TRADE",
                0.0,
                "no thesis",
                situation.opportunities,
                situation.risks,
                invalid_conditions or [],
            )
        action = (
            "OPEN_LONG"
            if direction == "LONG"
            else "OPEN_SHORT"
            if direction == "SHORT"
            else "NO_TRADE"
        )
        if challenge.decision_confidence < 0.35:
            action = "NO_TRADE"
        return TradingIntent(
            symbol,
            action,
            challenge.decision_confidence,
            thesis,
            (supporting or []) + situation.opportunities,
            (contradicting or []) + situation.risks,
            invalid_conditions or [],
        )
