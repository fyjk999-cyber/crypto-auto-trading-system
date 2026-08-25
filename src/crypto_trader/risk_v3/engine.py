"""Risk V3: 30% max drawdown, loss streak, daily loss, emergency mode."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class RiskDecisionV3:
    level: str
    drawdown_pct: Decimal
    new_risk_allowed: bool
    max_leverage: Decimal
    allow_reduce_close: bool = True
    reason: str = ""


class RiskV3:
    def __init__(self, max_drawdown: str = "30") -> None:
        self.max_drawdown = D(max_drawdown) / D("100")

    def evaluate(self, drawdown_pct) -> RiskDecisionV3:
        dd = abs(D(drawdown_pct)) / D("100")
        if dd < D("0.15"):
            return RiskDecisionV3("NORMAL", dd * 100, True, D("6"), "NORMAL")
        if dd < D("0.20"):
            return RiskDecisionV3(
                "CAUTION", dd * 100, True, D("3"), reason="REDUCE_POSITION_REDUCE_LEVERAGE"
            )
        if dd < self.max_drawdown:
            return RiskDecisionV3(
                "DEFENSIVE", dd * 100, False, D("1"), reason="HIGH_RISK_APPROVAL_REQUIRED"
            )
        return RiskDecisionV3("HALTED", dd * 100, False, D("0"), reason="MAX_DRAWDOWN_HALT")


class LossStreakGuard:
    def __init__(self) -> None:
        self.streak = 0

    def record_loss(self) -> int:
        self.streak += 1
        return self.streak

    def record_win(self) -> None:
        self.streak = 0

    def position_multiplier(self) -> Decimal:
        if self.streak >= 5:
            return D("0")
        if self.streak >= 3:
            return D("0.5")
        return D("1")


class DailyLossGuard:
    def __init__(self, daily_limit_pct: str = "3") -> None:
        self.daily_limit_pct = D(daily_limit_pct) / D("100")
        self.daily_pnl = D("0")

    def record_pnl(self, pnl) -> None:
        self.daily_pnl += D(pnl)

    def block_new_risk(self) -> bool:
        return self.daily_pnl <= -abs(self.daily_limit_pct)


class EmergencyRiskMode:
    def __init__(self) -> None:
        self.active = False
        self.reason = ""

    def trigger(self, reason: str) -> None:
        self.active = True
        self.reason = reason

    def reset(self) -> None:
        self.active = False
        self.reason = ""

    def new_risk_allowed(self) -> bool:
        return not self.active

    def reduce_close_allowed(self) -> bool:
        return True
