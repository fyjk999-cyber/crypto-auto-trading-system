"""Factor decay detector."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.models import FactorDecayResult


class FactorDecayDetector:
    def detect(
        self,
        *,
        factor_name: str,
        symbol: str,
        old_performance: Decimal,
        new_performance: Decimal,
        threshold: Decimal = Decimal("0.15"),
    ) -> FactorDecayResult:
        old = old_performance
        new = new_performance
        if old <= 0:
            return FactorDecayResult(
                factor_name, symbol, "TESTING", old, new, "insufficient history"
            )
        drop = (old - new) / old
        if drop >= threshold:
            return FactorDecayResult(
                factor_name, symbol, "DEGRADING", old, new, "performance decay"
            )
        if new < old * Decimal("0.9"):
            return FactorDecayResult(factor_name, symbol, "TESTING", old, new, "mild decline")
        return FactorDecayResult(factor_name, symbol, "HEALTHY", old, new, "stable")
