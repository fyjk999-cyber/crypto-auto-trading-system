"""Overall market intelligence confidence."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


class IntelligenceConfidence:
    def compute(
        self,
        *,
        regime_confidence: Decimal,
        factor_confidence_avg: Decimal,
        research_consensus_confidence: Decimal,
        data_quality: Decimal,
    ) -> Decimal:
        score = (
            D(regime_confidence) * D("0.25")
            + D(factor_confidence_avg) * D("0.35")
            + D(research_consensus_confidence) * D("0.25")
            + D(data_quality) * D("0.15")
        )
        return max(D("0"), min(D("1"), score))
