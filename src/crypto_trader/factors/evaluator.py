"""Factor evaluator: predictive quality and health status."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.models import FactorHealth, FactorPerformance


class FactorEvaluator:
    def evaluate(self, performance: FactorPerformance) -> FactorHealth:
        sample = performance.sample_size
        if sample < 30:
            status = "EXPERIMENTAL"
            reason = "low sample"
        elif performance.sharpe < Decimal("0.2") or performance.win_rate < Decimal("0.45"):
            status = "DEGRADING"
            reason = "weak performance"
        elif performance.win_rate < Decimal("0.52"):
            status = "TESTING"
            reason = "marginal performance"
        else:
            status = "HEALTHY"
            reason = "ok"
        return FactorHealth(performance.factor_name, performance.symbol, status, sample, reason)
