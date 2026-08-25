"""Factor combination evaluator: research-only."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.combinations.models import FactorCombination


class CombinationEvaluator:
    def evaluate(self, *, factors: list[str], observations: list[dict]) -> FactorCombination:
        name = "_".join(factors[:3])
        total = len(observations)
        wins = sum(1 for o in observations if o.get("result") == "WIN")
        win_rate = Decimal(wins) / Decimal(total) if total else Decimal("0")
        if total < 30:
            status = "TESTING"
        elif win_rate > Decimal("0.55"):
            status = "VALIDATED"
        else:
            status = "REJECTED"
        performance = {"sample_size": total, "win_rate": str(win_rate)}
        return FactorCombination(name=name, factors=factors, performance=performance, status=status)
