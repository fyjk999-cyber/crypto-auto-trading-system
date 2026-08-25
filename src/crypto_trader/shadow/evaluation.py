"""Shadow performance evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class ShadowMetrics:
    trade_count: int
    win_rate: Decimal
    profit_factor: Decimal
    average_return: Decimal
    max_drawdown: Decimal
    sharpe: Decimal
    sortino: Decimal
    ai_accuracy: Decimal


class ShadowEvaluator:
    def evaluate(self, closed_positions: list, predictions: list[dict]) -> ShadowMetrics:
        pnls = [D(str(p.pnl)) for p in closed_positions]
        if not pnls:
            return ShadowMetrics(
                0,
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
            )
        wins = [p for p in pnls if p > 0]
        losses = [-p for p in pnls if p < 0]
        avg = sum(pnls, Decimal("0")) / Decimal(len(pnls))
        peak = Decimal("0")
        max_dd = Decimal("0")
        running = Decimal("0")
        for p in pnls:
            running += p
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)
        std = (sum((p - avg) ** 2 for p in pnls) / Decimal(len(pnls))).sqrt()
        sharpe = avg / std * Decimal(len(pnls)).sqrt() if std > 0 else Decimal("0")
        downside = [p for p in pnls if p < 0]
        dstd = (
            (sum((p**2) for p in downside) / Decimal(len(downside))).sqrt()
            if downside
            else Decimal("0")
        )
        sortino = avg / dstd * Decimal(len(pnls)).sqrt() if dstd > 0 else Decimal("0")
        correct = sum(1 for p in predictions if p.get("result") == "CORRECT")
        accuracy = Decimal(correct) / Decimal(len(predictions)) if predictions else Decimal("0")
        return ShadowMetrics(
            trade_count=len(pnls),
            win_rate=Decimal(len(wins)) / Decimal(len(pnls)),
            profit_factor=(sum(wins, Decimal("0")) / sum(losses, Decimal("0")))
            if losses and sum(losses, Decimal("0")) > 0
            else Decimal("999"),
            average_return=avg,
            max_drawdown=max_dd,
            sharpe=sharpe,
            sortino=sortino,
            ai_accuracy=accuracy,
        )
