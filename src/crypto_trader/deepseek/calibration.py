"""Confidence calibration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class CalibrationResult:
    adjusted_confidence: Decimal
    accuracy: Decimal
    calibration_error: Decimal


def calibrate_confidence(
    *,
    confidence: Decimal,
    historical_accuracy: Decimal,
    symbol_accuracy: Decimal | None = None,
    regime_accuracy: Decimal | None = None,
) -> CalibrationResult:
    accuracy = D(historical_accuracy)
    adjusted = D(confidence) * accuracy
    error = abs(D(confidence) - accuracy)
    return CalibrationResult(
        adjusted_confidence=max(D("0.05"), min(D("0.95"), adjusted)),
        accuracy=accuracy,
        calibration_error=error,
    )
