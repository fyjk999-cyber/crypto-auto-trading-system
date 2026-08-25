"""Exposure calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class ExposureSnapshot:
    total_exposure: Decimal
    asset_concentration: dict[str, Decimal]
    strategy_exposure: dict[str, Decimal]


class ExposureEngine:
    def calculate(self, positions: list[dict]) -> ExposureSnapshot:
        total = sum((abs(D(str(p.get("notional", "0")))) for p in positions), D("0"))
        concentration = {}
        strategy = {}
        for p in positions:
            symbol = p["symbol"]
            notional = abs(D(str(p.get("notional", "0"))))
            concentration[symbol] = notional / total * D("100") if total > 0 else D("0")
            key = p.get("strategy", "unknown")
            strategy[key] = strategy.get(key, D("0")) + notional
        return ExposureSnapshot(
            total_exposure=total, asset_concentration=concentration, strategy_exposure=strategy
        )
