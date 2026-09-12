"""Trading thesis builder."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import TradingThesis


class ThesisBuilder:
    def build(
        self,
        *,
        symbol: str,
        direction: str,
        thesis: str,
        supporting: list[str] | None = None,
        contradicting: list[str] | None = None,
        confidence: float = 0.5,
        invalid_conditions: list[str] | None = None,
    ) -> TradingThesis:
        return TradingThesis(
            symbol=symbol,
            direction=direction,
            thesis=thesis,
            supporting_evidence=supporting or [],
            contradicting_evidence=contradicting or [],
            confidence=confidence,
            invalid_conditions=invalid_conditions or [],
        )
