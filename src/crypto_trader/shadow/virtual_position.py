"""Shadow virtual positions. No exchange orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class VirtualPosition:
    symbol: str
    direction: str  # LONG | SHORT
    entry_price: Decimal
    size: Decimal
    entry_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    exit_price: Decimal | None = None
    exit_time: str | None = None
    mae: Decimal = Decimal("0")
    mfe: Decimal = Decimal("0")
    pnl: Decimal = Decimal("0")

    def mark(self, price) -> Decimal:
        mark = D(price)
        if self.direction == "LONG":
            pnl = (mark - self.entry_price) * self.size
        else:
            pnl = (self.entry_price - mark) * self.size
        self.mfe = max(self.mfe, pnl)
        self.mae = min(self.mae, pnl)
        return pnl

    def close(self, price) -> Decimal:
        pnl = self.mark(price)
        self.exit_price = D(price)
        self.exit_time = datetime.now(UTC).isoformat()
        self.pnl = pnl
        return pnl

    def roi(self) -> Decimal:
        if self.exit_price is None or self.entry_price == 0:
            return Decimal("0")
        return (self.exit_price - self.entry_price) / self.entry_price * D("100")


class VirtualPositionBook:
    def __init__(self) -> None:
        self.positions: dict[str, VirtualPosition] = {}
        self.closed: list[VirtualPosition] = []

    def open(self, symbol: str, direction: str, entry_price, size) -> VirtualPosition:
        pos = VirtualPosition(
            symbol=symbol, direction=direction.upper(), entry_price=D(entry_price), size=D(size)
        )
        self.positions[symbol] = pos
        return pos

    def close(self, symbol: str, price) -> VirtualPosition | None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
        pos.close(price)
        self.closed.append(pos)
        return pos

    def all_pnl(self) -> Decimal:
        return sum((p.mae for p in self.positions.values()), Decimal("0"))
