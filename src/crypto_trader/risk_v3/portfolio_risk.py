"""Portfolio risk analytics: exposure, concentration, correlation proxy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class PortfolioRiskSnapshot:
    total_exposure: Decimal
    asset_concentration: dict[str, Decimal]
    strategy_exposure: dict[str, Decimal]
    correlation_risk: Decimal
    portfolio_beta: Decimal


class PortfolioRiskEngine:
    def analyze(self, positions: list[dict]) -> PortfolioRiskSnapshot:
        total = sum((abs(D(p.get("notional", "0"))) for p in positions), D("0"))
        concentration: dict[str, Decimal] = {}
        for p in positions:
            symbol = p["symbol"]
            notional = abs(D(p.get("notional", "0")))
            concentration[symbol] = notional / total * D("100") if total > 0 else D("0")
        strategy_exposure: dict[str, Decimal] = {}
        for p in positions:
            key = p.get("strategy", "unknown")
            strategy_exposure[key] = strategy_exposure.get(key, D("0")) + abs(
                D(p.get("notional", "0"))
            )
        correlation_risk = min(D("1"), total / D("1000000")) if total > 0 else D("0")
        beta = (
            sum((D(p.get("beta", "1")) for p in positions), D("0")) / Decimal(len(positions))
            if positions
            else D("0")
        )
        return PortfolioRiskSnapshot(
            total_exposure=total,
            asset_concentration=concentration,
            strategy_exposure=strategy_exposure,
            correlation_risk=correlation_risk,
            portfolio_beta=beta,
        )
