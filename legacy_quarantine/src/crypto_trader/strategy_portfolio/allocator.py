"""Strategy portfolio allocation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StrategyAllocation:
    strategy: str
    weight_pct: Decimal


class StrategyPortfolioAllocator:
    def allocate(
        self, *, regime: str, strategy_performance: dict[str, Decimal]
    ) -> list[StrategyAllocation]:
        if regime == "TREND_BULL":
            weights = {
                "trend_following": Decimal("50"),
                "momentum": Decimal("30"),
                "mean_reversion": Decimal("10"),
                "cash": Decimal("10"),
            }
        else:
            weights = {
                "trend_following": Decimal("30"),
                "mean_reversion": Decimal("40"),
                "momentum": Decimal("20"),
                "cash": Decimal("10"),
            }
        return [StrategyAllocation(k, v) for k, v in weights.items()]
