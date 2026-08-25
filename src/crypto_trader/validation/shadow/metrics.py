"""Shadow performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class ValidationMetrics:
    trade_count: int
    win_rate: Decimal
    profit_factor: Decimal
    sharpe: Decimal
    sortino: Decimal
    max_drawdown: Decimal
    average_return: Decimal
    long_accuracy: Decimal
    short_accuracy: Decimal


def calculate_metrics(closed_positions: list, predictions: list[dict]) -> ValidationMetrics:
    pnls = [p.pnl for p in closed_positions]
    if not pnls:
        return ValidationMetrics(0, D("0"), D("0"), D("0"), D("0"), D("0"), D("0"), D("0"), D("0"))
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    avg = sum(pnls, D("0")) / Decimal(len(pnls))
    std = (sum((p - avg) ** 2 for p in pnls) / Decimal(len(pnls))).sqrt()
    sharpe = avg / std * Decimal(len(pnls)).sqrt() if std > 0 else D("0")
    downside = [p for p in pnls if p < 0]
    dstd = (sum((p**2) for p in downside) / Decimal(len(downside))).sqrt() if downside else D("0")
    sortino = avg / dstd * Decimal(len(pnls)).sqrt() if dstd > 0 else D("0")
    peak = D("0")
    running = D("0")
    max_dd = D("0")
    for p in pnls:
        running += p
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    longs = [p for p in predictions if p.get("direction") == "LONG"]
    shorts = [p for p in predictions if p.get("direction") == "SHORT"]

    def acc(rows):
        if not rows:
            return D("0")
        return Decimal(sum(1 for r in rows if r.get("result") == "CORRECT")) / Decimal(len(rows))

    return ValidationMetrics(
        trade_count=len(pnls),
        win_rate=Decimal(len(wins)) / Decimal(len(pnls)),
        profit_factor=sum(wins, D("0")) / sum(losses, D("0"))
        if losses and sum(losses, D("0")) > 0
        else D("999"),
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        average_return=avg,
        long_accuracy=acc(longs),
        short_accuracy=acc(shorts),
    )
