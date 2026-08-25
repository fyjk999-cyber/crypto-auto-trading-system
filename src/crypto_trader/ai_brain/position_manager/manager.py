"""Position manager: dynamic hold/add/reduce/exit decisions."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import PositionDecision


class PositionManager:
    def decide(
        self,
        *,
        symbol: str,
        thesis_valid: bool,
        risk_increased: bool,
        opportunity_score: float,
        profit_factor: float = 0.0,
    ) -> PositionDecision:
        if not thesis_valid:
            return PositionDecision(symbol, "EXIT", "thesis invalidated", 0.8)
        if risk_increased:
            return PositionDecision(symbol, "REDUCE", "risk increased", 0.7)
        if opportunity_score > 0.7 and profit_factor < 1.5:
            return PositionDecision(symbol, "ADD", "strong opportunity", 0.6)
        return PositionDecision(symbol, "HOLD", "thesis intact", 0.65)
