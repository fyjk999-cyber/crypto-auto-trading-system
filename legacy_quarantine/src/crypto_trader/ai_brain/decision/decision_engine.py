"""Position-aware AI Trading Brain. Outputs TradingIntent only."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import TradingIntent
from crypto_trader.ai_brain.observation.observer import MarketObserver
from crypto_trader.ai_brain.position_manager.manager import PositionContext, PositionManager
from crypto_trader.ai_brain.reasoning.challenge import SelfChallenge
from crypto_trader.ai_brain.thesis.builder import ThesisBuilder


class AITradingBrain:
    def __init__(self) -> None:
        self.observer = MarketObserver()
        self.thesis_builder = ThesisBuilder()
        self.challenger = SelfChallenge()
        self.position_manager = PositionManager()

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
        active_position: dict | None = None,
    ) -> TradingIntent:
        situation = self.observer.observe(
            market_state=market_state, factor_intelligence=factor_intelligence, portfolio=portfolio
        )
        if active_position and float(active_position.get("quantity", 0)) > 0:
            return self._position_analysis(
                symbol=symbol,
                market_state=market_state,
                situation=situation,
                active_position=active_position,
                factor_intelligence=factor_intelligence or {},
            )
        return self._entry_analysis(
            symbol=symbol,
            market_state=market_state,
            situation=situation,
            direction=direction,
            thesis=thesis,
            supporting=supporting,
            contradicting=contradicting,
            confidence=confidence,
            invalid_conditions=invalid_conditions,
        )

    def _entry_analysis(
        self,
        *,
        symbol,
        market_state,
        situation,
        direction,
        thesis,
        supporting,
        contradicting,
        confidence,
        invalid_conditions,
    ) -> TradingIntent:
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
        if challenge.decision_confidence < 0.35:
            return TradingIntent(
                symbol,
                "NO_TRADE",
                challenge.decision_confidence,
                thesis,
                situation.opportunities,
                situation.risks + list(contradicting or []),
                invalid_conditions or [],
            )
        action = (
            "OPEN_LONG"
            if direction == "LONG"
            else "OPEN_SHORT"
            if direction == "SHORT"
            else "NO_TRADE"
        )
        return TradingIntent(
            symbol,
            action,
            challenge.decision_confidence,
            thesis,
            (supporting or []) + situation.opportunities,
            (contradicting or []) + situation.risks,
            invalid_conditions or [],
        )

    def _position_analysis(
        self, *, symbol, market_state, situation, active_position, factor_intelligence
    ) -> TradingIntent:
        side = str(active_position.get("side", "LONG")).upper()
        thesis_status = active_position.get("thesis_status", "THESIS_INTACT")
        ctx = PositionContext(
            symbol=symbol,
            position_side=side,
            position_quantity=float(active_position.get("quantity", 0)),
            entry_price=float(active_position.get("entry_price", 0)),
            current_price=float(active_position.get("current_price", 0)),
            unrealized_pnl=float(active_position.get("unrealized_pnl", 0)),
            realized_pnl=float(active_position.get("realized_pnl", 0)),
            time_in_position_seconds=float(active_position.get("age_seconds", 0)),
            original_thesis=active_position.get("thesis", ""),
            supporting_evidence=active_position.get("supporting", []),
            contradicting_evidence=active_position.get("contradicting", []),
            invalid_conditions=active_position.get("invalid_conditions", []),
            factor_intelligence=factor_intelligence,
            risk_context=active_position.get("risk_context", {}),
            thesis_status=thesis_status,
            hard_risk_exit=bool(active_position.get("hard_risk_exit", False)),
        )
        decision = self.position_manager.decide(ctx)
        return TradingIntent(
            symbol=symbol,
            action=decision.action if decision.action != "NO_ACTION" else "NO_TRADE",
            confidence=decision.confidence,
            thesis=active_position.get("thesis", ""),
            evidence=decision.supporting_evidence + situation.opportunities,
            risks=decision.contradicting_evidence + situation.risks + decision.risk_notes,
            invalid_conditions=active_position.get("invalid_conditions", []),
        )
