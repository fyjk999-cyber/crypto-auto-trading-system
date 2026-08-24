from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.governance.memory import TradeMemory


@dataclass
class DailyReviewStats:
    date: str
    daily_pnl: Decimal = Decimal("0")
    long_pnl: Decimal = Decimal("0")
    short_pnl: Decimal = Decimal("0")
    gross_pnl: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    funding_pnl: Decimal = Decimal("0")
    trade_count: int = 0
    win_rate: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")
    avg_r: Decimal = Decimal("0")
    failure_distribution: dict = None

    def __post_init__(self):
        if self.failure_distribution is None:
            self.failure_distribution = {}


class DailyReview:
    def __init__(self, memory: TradeMemory, failure_memory=None) -> None:
        self.memory = memory
        self.failure_memory = failure_memory

    def run(self, date: str | None = None) -> DailyReviewStats:
        date = date or datetime.now(UTC).date().isoformat()
        rows = [r for r in self.memory.all() if r.ts.date().isoformat() == date]
        stats = DailyReviewStats(date=date)
        stats.trade_count = len(rows)
        pnls = []
        for r in rows:
            pnl = r.realized_pnl or Decimal("0")
            pnls.append(pnl)
            stats.gross_pnl += pnl
            stats.fees += r.fees
            stats.funding_pnl += r.funding_pnl
            if r.side == "LONG":
                stats.long_pnl += pnl
            elif r.side == "SHORT":
                stats.short_pnl += pnl
        stats.net_pnl = stats.gross_pnl - stats.fees + stats.funding_pnl
        stats.daily_pnl = stats.net_pnl
        wins = [p for p in pnls if p > 0]
        losses = [-p for p in pnls if p < 0]
        stats.win_rate = Decimal(len(wins)) / Decimal(len(pnls)) if pnls else Decimal("0")
        gross_win = sum(wins, Decimal("0"))
        gross_loss = sum(losses, Decimal("0"))
        stats.profit_factor = gross_win / gross_loss if gross_loss > 0 else Decimal("999")
        stats.expectancy = sum(pnls, Decimal("0")) / Decimal(len(pnls)) if pnls else Decimal("0")
        stats.avg_r = (
            sum((r.r_multiple for r in rows), Decimal("0")) / Decimal(len(rows))
            if rows
            else Decimal("0")
        )
        if self.failure_memory is not None:
            stats.failure_distribution = self.failure_memory.distribution()
        return stats

    def strategy_regime_matrix(self) -> dict:
        matrix: dict[str, dict] = {}
        for r in self.memory.all():
            key = f"{r.side}@{r.regime}"
            cell = matrix.setdefault(key, {"trade_count": 0, "pnl": Decimal("0")})
            cell["trade_count"] += 1
            cell["pnl"] += r.realized_pnl or Decimal("0")
        return matrix
