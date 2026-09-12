"""Capital safety layer for future small-capital LIVE. LIVE disabled by default."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class CapitalGuard:
    max_capital_allocation_pct: str = "10"
    daily_loss_limit_pct: str = "2"
    emergency_stop: bool = False
    manual_approval_required: bool = True
    daily_pnl: Decimal = Decimal("0")

    def record_pnl(self, pnl) -> None:
        self.daily_pnl += D(pnl)

    def block_new_risk(self, equity, position_notional) -> tuple[bool, str]:
        if self.emergency_stop:
            return True, "EMERGENCY_STOP"
        if self.manual_approval_required:
            return True, "MANUAL_APPROVAL_REQUIRED"
        if D(equity) > 0:
            allocation = D(position_notional) / D(equity) * D("100")
            if allocation > D(self.max_capital_allocation_pct):
                return True, "MAX_CAPITAL_ALLOCATION"
        if self.daily_pnl <= -abs(D(self.daily_loss_limit_pct)):
            return True, "DAILY_LOSS_LIMIT"
        return False, "OK"
