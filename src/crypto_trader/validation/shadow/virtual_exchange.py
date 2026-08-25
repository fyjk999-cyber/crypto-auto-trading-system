"""Virtual execution engine for shadow validation. No exchange orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class VirtualPosition:
    symbol: str
    direction: str
    entry_price: Decimal
    size: Decimal
    fee: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    exit_price: Decimal | None = None
    pnl: Decimal = Decimal("0")
    roi: Decimal = Decimal("0")
    holding_time_seconds: float = 0.0
    opened_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    closed_at: str | None = None


class VirtualExecutionEngine:
    def __init__(self, fee_rate: str = "0.0005", slippage_bps: str = "2") -> None:
        self.fee_rate = D(fee_rate)
        self.slippage_bps = D(slippage_bps)
        self.open_positions: dict[str, VirtualPosition] = {}
        self.closed_positions: list[VirtualPosition] = []

    def open(self, symbol: str, direction: str, entry_price, size) -> VirtualPosition:
        entry = D(entry_price)
        qty = D(size)
        fee = entry * qty * self.fee_rate
        slip = entry * qty * self.slippage_bps / D("10000")
        pos = VirtualPosition(
            symbol=symbol,
            direction=direction.upper(),
            entry_price=entry,
            size=qty,
            fee=fee,
            slippage=slip,
        )
        self.open_positions[symbol] = pos
        return pos

    def close(self, symbol: str, exit_price) -> VirtualPosition | None:
        pos = self.open_positions.pop(symbol, None)
        if pos is None:
            return None
        exit_px = D(exit_price)
        fee = exit_px * pos.size * self.fee_rate
        slip = exit_px * pos.size * self.slippage_bps / D("10000")
        if pos.direction == "LONG":
            gross = (exit_px - pos.entry_price) * pos.size
        else:
            gross = (pos.entry_price - exit_px) * pos.size
        pos.pnl = gross - fee - slip - pos.fee - pos.slippage
        pos.exit_price = exit_px
        pos.roi = (
            pos.pnl / (pos.entry_price * pos.size) * D("100") if pos.entry_price > 0 else D("0")
        )
        pos.closed_at = datetime.now(UTC).isoformat()
        self.closed_positions.append(pos)
        return pos
