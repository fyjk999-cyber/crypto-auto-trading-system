"""AI risk committee policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class RiskPolicy:
    max_leverage_default: Decimal = Decimal("5")
    max_position_pct: Decimal = Decimal("10")
    max_drawdown_pct: Decimal = Decimal("15")
    small_cap_penalty: bool = True
    extreme_vol_penalty: bool = True
