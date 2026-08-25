"""Position intelligence: LONG/SHORT profit analytics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class PositionAnalytics:
    symbol: str
    direction: str
    entry_price: Decimal
    mark_price: Decimal
    size: Decimal
    leverage: Decimal
    margin: Decimal
    liquidation_price: Decimal | None
    margin_ratio: Decimal
    unrealized_pnl: Decimal
    roi: Decimal

    @staticmethod
    def analyze(
        symbol: str,
        direction: str,
        entry_price,
        mark_price,
        size,
        leverage,
        margin,
        liquidation_price=None,
        margin_ratio=None,
    ) -> PositionAnalytics:
        entry = D(entry_price)
        mark = D(mark_price)
        qty = D(size)
        lev = D(leverage)
        margin = D(margin)
        if direction.upper() == "LONG":
            pnl = (mark - entry) * qty
        else:
            pnl = (entry - mark) * qty
        roi = pnl / margin * D("100") if margin > 0 else D("0")
        return PositionAnalytics(
            symbol=symbol,
            direction=direction.upper(),
            entry_price=entry,
            mark_price=mark,
            size=qty,
            leverage=lev,
            margin=margin,
            liquidation_price=D(liquidation_price) if liquidation_price is not None else None,
            margin_ratio=D(margin_ratio) if margin_ratio is not None else Decimal("0"),
            unrealized_pnl=pnl,
            roi=roi,
        )


@dataclass
class LongShortProfit:
    total_long_pnl: Decimal = Decimal("0")
    total_short_pnl: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")

    def add(self, direction: str, pnl) -> None:
        if direction.upper() == "LONG":
            self.total_long_pnl += D(pnl)
        else:
            self.total_short_pnl += D(pnl)
        self.net_pnl = self.total_long_pnl + self.total_short_pnl
