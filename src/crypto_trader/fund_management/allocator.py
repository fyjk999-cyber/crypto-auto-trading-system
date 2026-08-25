"""Fund allocation and performance attribution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class FundAllocation:
    strategy: str
    weight_pct: Decimal
    max_risk_pct: Decimal


class FundAllocator:
    def allocate(self, budget: dict[str, Decimal]) -> list[FundAllocation]:
        total = sum((D(v) for v in budget.values()), D("0"))
        if total <= 0:
            return []
        return [
            FundAllocation(
                strategy=name,
                weight_pct=D(str(v)) / total * D("100"),
                max_risk_pct=D(str(v)) / total * D("100"),
            )
            for name, v in budget.items()
        ]

    def attribute_pnl(self, strategy_pnl: dict[str, Decimal]) -> dict[str, Decimal]:
        return {k: D(v) for k, v in strategy_pnl.items()}
