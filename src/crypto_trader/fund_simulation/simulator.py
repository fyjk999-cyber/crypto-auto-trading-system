"""12-month AI fund manager simulation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class SimulationResult:
    months: int
    return_pct: Decimal
    max_drawdown_pct: Decimal
    profit_factor: Decimal
    win_rate: Decimal
    decision_accuracy: Decimal


class FundSimulator:
    def run(self, *, months: int = 12, returns: list[Decimal]) -> SimulationResult:
        equity = Decimal("1")
        peak = Decimal("1")
        max_dd = Decimal("0")
        pnls = [D(r) for r in returns]
        for r in pnls:
            equity *= 1 + r
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)
        wins = [p for p in pnls if p > 0]
        losses = [-p for p in pnls if p < 0]
        pf = (
            sum(wins, D("0")) / sum(losses, D("0"))
            if losses and sum(losses, D("0")) > 0
            else D("999")
        )
        accuracy = Decimal(len(wins)) / Decimal(len(pnls)) if pnls else D("0")
        return SimulationResult(
            months=months,
            return_pct=(equity - Decimal("1")) * D("100"),
            max_drawdown_pct=max_dd * D("100"),
            profit_factor=pf,
            win_rate=accuracy,
            decision_accuracy=accuracy,
        )
