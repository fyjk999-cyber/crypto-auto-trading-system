"""Adaptive confidence governance."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class GovernedConfidence:
    original: Decimal
    calibrated: Decimal
    adjustment: Decimal


class ConfidenceGovernor:
    def govern(
        self,
        *,
        llm_confidence: Decimal,
        historical_success: Decimal,
        pattern_confidence: Decimal,
        coin_profile_confidence: Decimal,
        strategy_sharpe: Decimal,
        regime_confidence: Decimal,
    ) -> GovernedConfidence:
        original = D(llm_confidence)
        base = (
            D("0.5") * historical_success
            + D("0.2") * pattern_confidence
            + D("0.15") * coin_profile_confidence
            + D("0.15") * regime_confidence
        )
        calibrated = original * base
        calibrated = max(D("0.05"), min(D("0.95"), calibrated))
        return GovernedConfidence(
            original=original, calibrated=calibrated, adjustment=calibrated - original
        )
