"""Decision calibration engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class CalibrationResult:
    calibrated_confidence: Decimal
    original_confidence: Decimal
    historical_accuracy: Decimal


class DecisionCalibrationEngine:
    def calibrate(
        self,
        *,
        llm_confidence: Decimal,
        historical_accuracy: Decimal,
        pattern_confidence: Decimal,
        coin_profile_confidence: Decimal,
        regime_confidence: Decimal,
    ) -> CalibrationResult:
        original = D(llm_confidence)
        accuracy = D(historical_accuracy)
        pattern = D(pattern_confidence)
        coin = D(coin_profile_confidence)
        regime = D(regime_confidence)
        calibrated = original * (
            D("0.5") * accuracy + D("0.2") * pattern + D("0.15") * coin + D("0.15") * regime
        )
        calibrated = max(D("0.05"), min(D("0.95"), calibrated))
        return CalibrationResult(
            calibrated_confidence=calibrated,
            original_confidence=original,
            historical_accuracy=accuracy,
        )
