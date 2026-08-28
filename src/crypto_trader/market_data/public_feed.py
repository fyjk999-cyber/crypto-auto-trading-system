"""Credential-free public market-data feeds."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.domain.money import D
from crypto_trader.exchange.binance_futures_public import (
    BinancePublicDataUnavailable,
    BinanceUSDMFuturesPublicClient,
)
from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.okx_public_data import OKXPublicDataClient
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


class OKXPublicMarketFeed:
    """Credential-free OKX SWAP market state for canonical PAPER runtime."""

    def __init__(self, symbol: str = "BTCUSDT", client: OKXAdapter | None = None) -> None:
        self.symbol = symbol
        self.mapper = SymbolMapper()
        self.client = client or OKXAdapter()
        self.public_data = OKXPublicDataClient(self.client)
        self.state = MarketState(symbol=symbol, source="OKX_PUBLIC", exchange="OKX")
        self._oi_prev: Decimal | None = None

    def _healthy(self, name: str, now: datetime) -> None:
        self.state.sources[name] = SourceStatus(
            source="OKX_PUBLIC",
            status=DataHealth.HEALTHY,
            age_seconds=0,
            updated_at=now,
            data_source="REAL",
        )

    @staticmethod
    def _optional_decimal(value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return D(str(value))
        except (ValueError, ArithmeticError):
            return None

    async def refresh(self) -> MarketState:
        now = datetime.now(UTC)
        inst_id = self.mapper.to_okx(self.symbol)
        index_id = inst_id.removesuffix("-SWAP")
        try:
            ticker = await self.public_data.get_ticker(inst_id)
            book_payload = await self.client.get_orderbook(inst_id)
            book_raw = book_payload["data"][0]
            bids = [(D(row[0]), D(row[1])) for row in book_raw.get("bids", [])]
            asks = [(D(row[0]), D(row[1])) for row in book_raw.get("asks", [])]
            book = OrderBook(symbol=self.symbol, exchange="OKX")
            book.apply_snapshot(int(book_raw.get("ts", "0")), bids, asks, now=now)
            bid, ask = book.best_bid(), book.best_ask()
            self.state.best_bid = bid.price if bid else D("0")
            self.state.best_ask = ask.price if ask else D("0")
            self.state.price = D(ticker.get("last", "0"))
            self.state.open_24h = self._optional_decimal(ticker.get("open_24h"))
            self.state.high_24h = self._optional_decimal(ticker.get("high_24h"))
            self.state.low_24h = self._optional_decimal(ticker.get("low_24h"))
            self.state.volume_24h = self._optional_decimal(ticker.get("volume_24h"))
            self.state.volume_ccy_24h = self._optional_decimal(
                ticker.get("volume_ccy_24h")
            )
            self.state.volume = self.state.volume_24h or D("0")
            self.state.last_size = self._optional_decimal(ticker.get("last_size"))
            self.state.best_bid_size = self._optional_decimal(ticker.get("bid_size"))
            self.state.best_ask_size = self._optional_decimal(ticker.get("ask_size"))
            self.state.open_utc0 = self._optional_decimal(ticker.get("open_utc0"))
            self.state.open_utc8 = self._optional_decimal(ticker.get("open_utc8"))
            self.state.compute_24h_change()
            self.state.spread = self.state.best_ask - self.state.best_bid
            self.state.depth = sum(
                (level.quantity for level in book.bids.values()), D("0")
            ) + sum((level.quantity for level in book.asks.values()), D("0"))
            if self.state.depth > 0:
                bid_depth = sum((level.quantity for level in book.bids.values()), D("0"))
                ask_depth = sum((level.quantity for level in book.asks.values()), D("0"))
                self.state.imbalance = (bid_depth - ask_depth) / self.state.depth
            self._healthy("ticker", now)
            self._healthy("orderbook", now)

            mark = await self.client.get_public_mark_price(inst_id)
            index = await self.client.get_public_index_ticker(index_id)
            funding = await self.client.get_public_funding_rate(inst_id)
            oi = await self.client.get_public_open_interest(inst_id)
            self.state.mark_price = D(mark.get("markPx", "0"))
            self.state.index_price = D(index.get("idxPx", "0"))
            self.state.funding_rate = self._optional_decimal(funding.get("fundingRate"))
            funding_time = funding.get("fundingTime") or funding.get("nextFundingTime")
            if funding_time:
                self.state.next_funding_time = datetime.fromtimestamp(
                    int(funding_time) / 1000.0, tz=UTC
                )
            current_oi = self._optional_decimal(oi.get("oi"))
            if current_oi is not None and self._oi_prev is not None:
                self.state.open_interest_change = current_oi - self._oi_prev
            self.state.open_interest = current_oi
            self.state.open_interest_ccy = self._optional_decimal(oi.get("oiCcy"))
            self.state.open_interest_usd = self._optional_decimal(oi.get("oiUsd"))
            self._oi_prev = current_oi
            for name in ("mark_price", "index_price", "funding", "open_interest"):
                self._healthy(name, now)
        except Exception as exc:
            self.state.invalidate(f"OKX_PUBLIC_UNAVAILABLE: {type(exc).__name__}")
            raise
        self.state.compute_basis()
        self.state.timestamp = now
        self.state.exchange_timestamp = now
        self.state.received_timestamp = now
        self.state.mark_healthy_from_sources()
        return self.state

    async def close(self) -> None:
        await self.client.disconnect()
