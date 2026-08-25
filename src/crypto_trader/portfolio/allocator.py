"""Portfolio allocator: risk budget based on asset category."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class Allocation:
    symbol: str
    weight_pct: Decimal
    risk_budget_pct: Decimal


class Allocator:
    CATEGORY_RISK = {"LARGE_CAP": "0.6", "MID_CAP": "0.8", "MEME": "1.5", "LOW_CAP": "1.5"}

    def allocate(self, assets: list[dict]) -> list[Allocation]:
        total_risk = sum(
            (D(self.CATEGORY_RISK.get(a.get("category", "LARGE_CAP"), "1")) for a in assets),
            D("0"),
        )
        if total_risk <= 0:
            return []
        return [
            Allocation(
                symbol=a["symbol"],
                weight_pct=risk / total_risk * D("100"),
                risk_budget_pct=risk * D("100"),
            )
            for a in assets
            for risk in [D(self.CATEGORY_RISK.get(a.get("category", "LARGE_CAP"), "1"))]
        ]
