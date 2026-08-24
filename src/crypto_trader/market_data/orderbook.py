"""Decimal-native normalized orderbook with sequence validation.

PORTED from Kalshi v2 lib/v2/orderbook.mjs normalization ideas:
- levels are (price, quantity) with Decimal amounts
- a book has an explicit sequence and staleness state
- any sequence gap invalidates the book before consumers can use it
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.enums import MarketDataStatus
from crypto_trader.domain.errors import SequenceGap, StaleMarketData
from crypto_trader.domain.money import D, format_decimal


class BookLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Decimal
    quantity: Decimal


class OrderBook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    sequence: int | None = None
    bids: dict[str, BookLevel] = Field(default_factory=dict)
    asks: dict[str, BookLevel] = Field(default_factory=dict)
    status: MarketDataStatus = MarketDataStatus.HEALTHY
    updated_at: datetime | None = None
    exchange: str = "UNKNOWN"

    def _upsert(self, levels: dict[str, BookLevel], updates: list[tuple[Decimal, Decimal]]) -> None:
        for raw_price, raw_qty in updates:
            price = D(raw_price)
            qty = D(raw_qty)
            if qty < 0:
                raise ValueError("orderbook quantity must be non-negative")
            key = format_decimal(price)
            if qty == 0:
                levels.pop(key, None)
            else:
                levels[key] = BookLevel(price=price, quantity=qty)

    def _sorted(self, levels: dict[str, BookLevel], *, reverse: bool) -> list[BookLevel]:
        return sorted(levels.values(), key=lambda level: level.price, reverse=reverse)

    def apply_snapshot(
        self,
        sequence: int,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        *,
        now: datetime | None = None,
    ) -> None:
        self.sequence = int(sequence)
        self.bids.clear()
        self.asks.clear()
        self._upsert(self.bids, bids)
        self._upsert(self.asks, asks)
        self.status = MarketDataStatus.HEALTHY
        self.updated_at = now or datetime.now(UTC)

    def apply_delta(
        self,
        sequence: int,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        *,
        now: datetime | None = None,
    ) -> None:
        if self.sequence is not None and int(sequence) != self.sequence + 1:
            raise SequenceGap(
                f"{self.symbol} sequence gap: expected {self.sequence + 1}, got {sequence}"
            )
        self._upsert(self.bids, bids)
        self._upsert(self.asks, asks)
        self.sequence = int(sequence)
        self.updated_at = now or datetime.now(UTC)

    def invalidate(self) -> None:
        self.status = MarketDataStatus.UNHEALTHY
        self.sequence = None
        self.bids.clear()
        self.asks.clear()
        self.updated_at = datetime.now(UTC)

    def ensure_fresh(self, max_age_seconds: float, now: datetime | None = None) -> None:
        if self.status != MarketDataStatus.HEALTHY:
            raise StaleMarketData(f"{self.symbol} orderbook status {self.status.value}")
        if self.updated_at is None:
            raise StaleMarketData(f"{self.symbol} orderbook has no snapshot")
        now = now or datetime.now(UTC)
        if (now - self.updated_at).total_seconds() > max_age_seconds:
            raise StaleMarketData(f"{self.symbol} orderbook older than {max_age_seconds}s")

    def best_bid(self) -> BookLevel | None:
        levels = self._sorted(self.bids, reverse=True)
        return levels[0] if levels else None

    def best_ask(self) -> BookLevel | None:
        levels = self._sorted(self.asks, reverse=False)
        return levels[0] if levels else None

    def mid_price(self) -> Decimal | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid.price + ask.price) / Decimal("2")

    def snapshot(self) -> dict:
        return {
            "symbol": self.symbol,
            "sequence": self.sequence,
            "status": self.status.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "bids": [
                [format_decimal(level.price), format_decimal(level.quantity)]
                for level in self._sorted(self.bids, reverse=True)[:25]
            ],
            "asks": [
                [format_decimal(level.price), format_decimal(level.quantity)]
                for level in self._sorted(self.asks, reverse=False)[:25]
            ],
        }
