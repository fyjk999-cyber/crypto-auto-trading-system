"""Exposure calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.exposure.service import ExposureService


@dataclass
class ExposureSnapshot:
    total_exposure: Decimal
    asset_concentration: dict[str, Decimal]
    strategy_exposure: dict[str, Decimal]


class ExposureEngine:
    def calculate(self, positions: list[dict]) -> ExposureSnapshot:
        notionals = [ExposureService.for_mapping(position).gross_notional for position in positions]
        total = sum(notionals, D("0"))
        concentration = {}
        strategy = {}
        for p, notional in zip(positions, notionals, strict=True):
            symbol = p["symbol"]
            concentration[symbol] = notional / total * D("100") if total > 0 else D("0")
            key = p.get("strategy", "unknown")
            strategy[key] = strategy.get(key, D("0")) + notional
        return ExposureSnapshot(
            total_exposure=total, asset_concentration=concentration, strategy_exposure=strategy
        )
