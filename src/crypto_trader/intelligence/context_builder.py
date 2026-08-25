"""Market intelligence context builder."""

from __future__ import annotations

from crypto_trader.intelligence.models import MarketIntelligenceContext


class MarketIntelligenceContextBuilder:
    def build(
        self,
        *,
        symbol: str,
        regime: dict,
        summary: dict,
        confidence: dict,
        positive_evidence: list[str] | None = None,
        negative_evidence: list[str] | None = None,
        research_summary: dict | None = None,
        similarity: dict | None = None,
        overall_confidence: float = 0.5,
    ) -> MarketIntelligenceContext:
        return MarketIntelligenceContext(
            symbol=symbol,
            market_regime=regime,
            factor_summary=summary,
            factor_confidence=confidence,
            positive_evidence=positive_evidence or [],
            negative_evidence=negative_evidence or [],
            research_summary=research_summary or {},
            historical_similarity=similarity or {},
            overall_confidence=overall_confidence,
        )
