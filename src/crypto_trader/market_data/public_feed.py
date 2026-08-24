"""Binance USD-M public market-data feed (REST polling, keyless)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.domain.money import D
from crypto_trader.exchange.binance_futures_public import (
    BinancePublicDataUnavailable,
    BinanceUSDMFuturesPublicClient,
)
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.state import DataHealth, MarketState, SourceStatus


class BinancePublicMarketFeed:
    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self.symbol = symbol
        self.client = BinanceUSDMFuturesPublicClient()
        self.state = MarketState(symbol=symbol)
        self._oi_prev: dict[str, Decimal] = {}
        self._klines_loaded = 0

    async def warmup(self, mde: MarketDataEngine, bars: int = 300, interval: str = "1m") -> int:
        try:
            raw = await self.client.get_klines(self.symbol, interval=interval, limit=bars)
        except BinancePublicDataUnavailable:
            self.state.sources["klines"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.UNAVAILABLE,
                age_seconds=-1,
                updated_at=datetime.now(UTC),
            )
            return 0
        loaded = 0
        for row in raw:
            ts = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=UTC)
            close = D(row[4])
            volume = D(row[5])
            mde.ingest(ts, close, volume)
            loaded += 1
        self._klines_loaded = loaded
        self.state.sources["klines"] = SourceStatus(
            source="BINANCE_USDM_PUBLIC",
            status=DataHealth.HEALTHY,
            age_seconds=0,
            updated_at=datetime.now(UTC),
        )
        return loaded

    async def refresh(self) -> MarketState:
        now = datetime.now(UTC)
        try:
            book_raw = await self.client.get_orderbook(self.symbol)
            book_norm = BinanceUSDMFuturesPublicClient.normalize_orderbook(book_raw)
            book = OrderBook(symbol=self.symbol)
            book.apply_snapshot(
                book_norm["sequence"], book_norm["bids"], book_norm["asks"], now=now
            )
            bid = book.best_bid()
            ask = book.best_ask()
            self.state.best_bid = bid.price if bid else D("0")
            self.state.best_ask = ask.price if ask else D("0")
            self.state.price = (
                (self.state.best_bid + self.state.best_ask) / D("2")
                if bid and ask
                else self.state.price
            )
            self.state.spread = self.state.best_ask - self.state.best_bid
            self.state.depth = sum(
                (level.quantity for level in book.bids.values()), Decimal("0")
            ) + sum((level.quantity for level in book.asks.values()), Decimal("0"))
            self.state.sources["orderbook"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.HEALTHY,
                age_seconds=0,
                updated_at=now,
            )
        except BinancePublicDataUnavailable:
            self.state.sources["orderbook"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.UNAVAILABLE,
                age_seconds=-1,
                updated_at=now,
            )

        try:
            mark = self.client.normalize_mark_price(await self.client.get_mark_price(self.symbol))
            self.state.mark_price = mark["mark_price"]
            self.state.index_price = mark["index_price"]
            self.state.funding_rate = mark["funding_rate"]
            self.state.next_funding_time = mark["next_funding_time"]
            self.state.sources["mark_price"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.HEALTHY,
                age_seconds=0,
                updated_at=now,
            )
        except BinancePublicDataUnavailable:
            self.state.sources["mark_price"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.UNAVAILABLE,
                age_seconds=-1,
                updated_at=now,
            )

        try:
            oi = self.client.normalize_open_interest(
                await self.client.get_open_interest(self.symbol)
            )
            current = oi["open_interest"]
            previous = self._oi_prev.get(self.symbol)
            if previous is not None:
                self.state.open_interest_change = current - previous
            self.state.open_interest = current
            self._oi_prev[self.symbol] = current
            self.state.sources["open_interest"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.HEALTHY,
                age_seconds=0,
                updated_at=now,
            )
        except BinancePublicDataUnavailable:
            self.state.sources["open_interest"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.UNAVAILABLE,
                age_seconds=-1,
                updated_at=now,
            )

        try:
            trades = await self.client.get_aggregate_trades(self.symbol, limit=100)
            volume = sum((D(str(t.get("q", "0"))) for t in trades), Decimal("0"))
            self.state.trade_volume = volume
            self.state.sources["trades"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.HEALTHY,
                age_seconds=0,
                updated_at=now,
            )
        except BinancePublicDataUnavailable:
            self.state.sources["trades"] = SourceStatus(
                source="BINANCE_USDM_PUBLIC",
                status=DataHealth.UNAVAILABLE,
                age_seconds=-1,
                updated_at=now,
            )

        self.state.compute_basis()
        self.state.health = self.state.overall_health()
        self.state.received_timestamp = now
        self.state.version += 1
        return self.state

    async def close(self) -> None:
        await self.client.close()
