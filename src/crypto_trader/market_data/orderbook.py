"""Decimal-native normalized orderbook with sequence validation.

PORTED from the reference v2 orderbook module normalization ideas:
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

    def top_levels(
        self, *, side: str, levels: int
    ) -> list[tuple[Decimal, Decimal]]:
        """Best-first factual ``(price, quantity)`` levels for one book side.

        Best-first means highest price for ``BID`` and lowest price for ``ASK``.
        An invalid side or a non-positive ``levels`` yields an empty list; the
        caller decides how to fail closed.
        """
        if not isinstance(levels, int) or isinstance(levels, bool) or levels < 1:
            return []
        book_side = str(side).upper()
        if book_side == "ASK":
            ordered = self._sorted(self.asks, reverse=False)
        elif book_side == "BID":
            ordered = self._sorted(self.bids, reverse=True)
        else:
            return []
        return [(level.price, level.quantity) for level in ordered[:levels]]

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

    def depth_quantity(self, *, side: str, levels: int) -> Decimal | None:
        """Aggregated factual quantity over the best ``levels`` levels.

        ``side`` is the side the caller would CONSUME: ``"ASK"`` for a buy
        (LONG entry) and ``"BID"`` for a sell (SHORT entry).

        Returns ``None`` — UNKNOWN, never zero-as-a-fact — when the book is not
        HEALTHY, when the requested side has no levels, when ``levels`` is not
        positive, or when the factual aggregate is not positive.  Callers must
        fail closed on ``None``: liquidity is never assumed infinite (§22).
        """
        if self.status != MarketDataStatus.HEALTHY:
            return None
        if not isinstance(levels, int) or isinstance(levels, bool) or levels < 1:
            return None
        book_side = str(side).upper()
        if book_side == "ASK":
            ordered = self._sorted(self.asks, reverse=False)
        elif book_side == "BID":
            ordered = self._sorted(self.bids, reverse=True)
        else:
            return None
        if not ordered:
            return None
        total = sum((level.quantity for level in ordered[:levels]), Decimal("0"))
        if total <= 0:
            return None
        return total

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
