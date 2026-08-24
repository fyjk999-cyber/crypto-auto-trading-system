"""MarketDataService: snapshot + continuous delta with gap detection and resync."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal

from crypto_trader.domain.enums import MarketDataStatus
from crypto_trader.domain.errors import MarketDataUnhealthy, SequenceGap
from crypto_trader.market_data.orderbook import OrderBook


class MarketDataService:
    def __init__(self, snapshot_provider=None) -> None:
        self.books: dict[str, OrderBook] = {}
        self.statuses: dict[str, MarketDataStatus] = {}
        self.snapshot_provider = snapshot_provider
        self.resync_errors: dict[str, list[str]] = {}
        # deltas received while resyncing are buffered and replayed in order
        self.resync_buffers: dict[str, deque] = {}

    def ensure_symbol(self, symbol: str, exchange: str = "UNKNOWN") -> OrderBook:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol=symbol, exchange=exchange)
            self.statuses[symbol] = MarketDataStatus.UNHEALTHY
            self.resync_buffers[symbol] = deque()
        return self.books[symbol]

    def _set_status(self, symbol: str, status: MarketDataStatus) -> None:
        self.statuses[symbol] = status
        if symbol in self.books:
            self.books[symbol].status = status

    async def ingest_snapshot(self, symbol: str, sequence: int,
                              bids: list[tuple[Decimal, Decimal]],
                              asks: list[tuple[Decimal, Decimal]]) -> OrderBook:
        book = self.ensure_symbol(symbol)
        book.apply_snapshot(sequence, bids, asks)
        self._set_status(symbol, MarketDataStatus.HEALTHY)
        # replay buffered continuous deltas received during resync
        while self.resync_buffers.get(symbol):
            seq, b, a = self.resync_buffers[symbol].popleft()
            try:
                book.apply_delta(seq, b, a)
            except SequenceGap:
                book.invalidate()
                self._set_status(symbol, MarketDataStatus.UNHEALTHY)
                raise
        return book

    async def ingest_delta(self, symbol: str, sequence: int,
                           bids: list[tuple[Decimal, Decimal]],
                           asks: list[tuple[Decimal, Decimal]]) -> OrderBook:
        book = self.ensure_symbol(symbol)
        if book.status == MarketDataStatus.RESYNCING:
            self.resync_buffers[symbol].append((sequence, bids, asks))
            return book
        if book.sequence is None:
            # no snapshot yet: first try resync, otherwise buffer as gap
            try:
                await self.resync(symbol)
            except MarketDataUnhealthy:
                raise
            if book.sequence is None or sequence != book.sequence + 1:
                book.invalidate()
                self._set_status(symbol, MarketDataStatus.UNHEALTHY)
                raise SequenceGap(f"{symbol} delta before valid snapshot or non-contiguous")
        try:
            book.apply_delta(sequence, bids, asks)
        except SequenceGap as exc:
            await self._handle_gap(symbol, exc)
        self._set_status(symbol, book.status)
        return book

    async def _handle_gap(self, symbol: str, exc: SequenceGap) -> None:
        self.resync_errors.setdefault(symbol, []).append(str(exc))
        book = self.books[symbol]
        book.invalidate()
        self._set_status(symbol, MarketDataStatus.RESYNCING)
        try:
            await self.resync(symbol)
        except MarketDataUnhealthy:
            raise
        if book.status != MarketDataStatus.HEALTHY:
            raise MarketDataUnhealthy(f"{symbol} failed to resync after sequence gap")

    async def resync(self, symbol: str) -> OrderBook:
        book = self.ensure_symbol(symbol)
        self._set_status(symbol, MarketDataStatus.RESYNCING)
        if self.snapshot_provider is None:
            self._set_status(symbol, MarketDataStatus.UNHEALTHY)
            raise MarketDataUnhealthy(f"{symbol}: no snapshot provider configured")
        try:
            snapshot = await self.snapshot_provider(symbol)
        except Exception as exc:
            self._set_status(symbol, MarketDataStatus.UNHEALTHY)
            self.resync_errors.setdefault(symbol, []).append(f"resync failed: {exc}")
            raise MarketDataUnhealthy(f"{symbol} resync failed") from exc
        # provider returns dict with sequence/bids/asks or an OrderBook
        if isinstance(snapshot, OrderBook):
            book.bids = snapshot.bids
            book.asks = snapshot.asks
            book.sequence = snapshot.sequence
            book.updated_at = datetime.now(timezone.utc)
        else:
            await self.ingest_snapshot(symbol, snapshot["sequence"], snapshot["bids"], snapshot["asks"])
        self._set_status(symbol, MarketDataStatus.HEALTHY)
        return book

    def is_healthy(self, symbol: str) -> bool:
        return self.statuses.get(symbol) == MarketDataStatus.HEALTHY and (
            symbol in self.books and self.books[symbol].status == MarketDataStatus.HEALTHY
        )

    def is_fresh(self, symbol: str, max_age_seconds: float, now: datetime | None = None) -> bool:
        book = self.books.get(symbol)
        if book is None or not self.is_healthy(symbol):
            return False
        if book.updated_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - book.updated_at).total_seconds() <= max_age_seconds

    def health(self) -> dict:
        return {
            symbol: {
                "status": status.value,
                "sequence": self.books[symbol].sequence if symbol in self.books else None,
            }
            for symbol, status in self.statuses.items()
        }
