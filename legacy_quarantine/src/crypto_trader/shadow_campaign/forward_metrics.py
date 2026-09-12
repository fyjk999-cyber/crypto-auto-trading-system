"""Forward shadow metrics and label maturity helpers. No lookahead."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class ForwardMetrics:
    total_trades: int = 0
    win_rate: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    sharpe: Decimal = Decimal("0")
    calibration_bucket_wins: dict = field(default_factory=dict)
    calibration_bucket_total: dict = field(default_factory=dict)

    def record(self, *, confidence: float, result: str, pnl: Decimal) -> None:
        self.total_trades += 1
        bucket = min(0.95, max(0.5, round(confidence * 20) / 20))
        self.calibration_bucket_total[bucket] = self.calibration_bucket_total.get(bucket, 0) + 1
        if result == "WIN":
            self.calibration_bucket_wins[bucket] = self.calibration_bucket_wins.get(bucket, 0) + 1
        self.net_pnl += D(pnl)
        if self.total_trades == 1:
            self.win_rate = D("1") if result == "WIN" else D("0")
            self.expectancy = D(pnl)
        else:
            self.win_rate = (
                self.win_rate * D(str(self.total_trades - 1))
                + (D("1") if result == "WIN" else D("0"))
            ) / D(str(self.total_trades))
            self.expectancy = self.net_pnl / D(str(self.total_trades))

    def calibration_ratio(self) -> str:
        for bucket in sorted(self.calibration_bucket_total):
            wins = self.calibration_bucket_wins.get(bucket, 0)
            total = self.calibration_bucket_total[bucket]
            if total >= 5 and wins / total < 0.45:
                return "OVERCONFIDENCE_RISK"
        return "PASS" if self.calibration_bucket_total else "INSUFFICIENT_EVIDENCE"

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "win_rate": str(self.win_rate),
            "profit_factor": str(self.profit_factor),
            "expectancy": str(self.expectancy),
            "net_pnl": str(self.net_pnl),
            "max_drawdown": str(self.max_drawdown),
            "sharpe": str(self.sharpe),
            "calibration": self.calibration_ratio(),
        }
