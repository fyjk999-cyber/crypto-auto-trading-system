"""Research-only out-of-sample evaluation contract (no execution authority)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OOSResult:
    train_metric: Decimal
    validation_metric: Decimal
    test_metric: Decimal
    passed: bool

    @property
    def degradation(self) -> Decimal:
        return self.train_metric - self.test_metric


def evaluate_oos(
    *, train_metric: Decimal, validation_metric: Decimal, test_metric: Decimal,
    min_test_metric: Decimal = Decimal("0"),
) -> OOSResult:
    passed = test_metric >= min_test_metric
    return OOSResult(
        train_metric=train_metric,
        validation_metric=validation_metric,
        test_metric=test_metric,
        passed=passed,
    )
