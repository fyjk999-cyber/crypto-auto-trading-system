"""Factor performance tracker."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class TradeObservation:
    factor_name: str
    factor_value: Decimal
    result_pnl: Decimal
    result: str  # WIN | LOSS


class FactorPerformanceTracker:
    def __init__(self) -> None:
        self.observations: list[TradeObservation] = []

    def record(self, observation: TradeObservation) -> None:
        self.observations.append(observation)

    def compute(self, factor_name: str, symbol: str, timeframe: str = "15m") -> dict:
        rows = [o for o in self.observations if o.factor_name == factor_name]
        if not rows:
            return {
                "factor_name": factor_name,
                "symbol": symbol,
                "timeframe": timeframe,
                "sample_size": 0,
                "win_rate": D("0"),
                "average_return": D("0"),
                "sharpe": D("0"),
                "max_drawdown": D("0"),
                "profit_factor": D("0"),
                "timestamp": "",
            }
        wins = [o for o in rows if o.result == "WIN"]
        losses = [o for o in rows if o.result == "LOSS"]
        pnls = [o.result_pnl for o in rows]
        avg = sum(pnls, D("0")) / D(str(len(pnls)))
        std = (
            (sum((p - avg) ** 2 for p in pnls) / D(str(len(pnls)))).sqrt()
            if len(pnls) > 1
            else D("0")
        )
        sharpe = avg / std * D(str(len(pnls))).sqrt() if std > 0 else D("0")
        peak = D("0")
        running = D("0")
        max_dd = D("0")
        for p in pnls:
            running += p
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)
        gross_win = sum((o.result_pnl for o in wins), D("0"))
        gross_loss = sum((-o.result_pnl for o in losses), D("0"))
        pf = gross_win / gross_loss if gross_loss > 0 else D("999")
        return {
            "factor_name": factor_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "sample_size": len(rows),
            "win_rate": D(str(len(wins))) / D(str(len(rows))),
            "average_return": avg,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "profit_factor": pf,
            "timestamp": "",
        }
