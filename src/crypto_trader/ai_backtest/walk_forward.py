"""Walk-forward validation. No future leakage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class WalkForwardReport:
    train_accuracy: Decimal
    validation_accuracy: Decimal
    oos_accuracy: Decimal
    confidence_adjustment: Decimal
    passed: bool
    reason: str


class WalkForwardValidator:
    def validate(
        self, *, train_results: list[dict], validation_results: list[dict], oos_results: list[dict]
    ) -> WalkForwardReport:
        def accuracy(rows):
            if not rows:
                return Decimal("0")
            correct = sum(1 for r in rows if r.get("result") == "CORRECT")
            return Decimal(correct) / Decimal(len(rows))

        train = accuracy(train_results)
        val = accuracy(validation_results)
        oos = accuracy(oos_results)
        degradation = train - oos
        passed = oos >= train * D("0.7") and oos >= Decimal("0.5")
        adjustment = max(D("0"), degradation)
        reason = "PASS" if passed else "OOS_DEGRADED"
        return WalkForwardReport(
            train_accuracy=train,
            validation_accuracy=val,
            oos_accuracy=oos,
            confidence_adjustment=adjustment,
            passed=passed,
            reason=reason,
        )
