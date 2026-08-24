"""PAPER_REAL_MARKET adapter: real public Binance USD-M data + simulated execution."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.exchange.binance_futures_public import (
    BinancePublicDataUnavailable,
    BinanceUSDMFuturesPublicClient,
)
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.public_feed import BinancePublicMarketFeed
from crypto_trader.market_data.state import MarketState
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter


class PaperRealMarketAdapter(SimulatedExchangeAdapter):
    """Real public market data; paper fills via the simulated exchange."""

    def __init__(
        self,
        *,
        initial_balances=None,
        instruments=None,
        feed: BinancePublicMarketFeed | None = None,
    ) -> None:
        super().__init__(initial_balances=initial_balances, instruments=instruments)
        self.feed = feed or BinancePublicMarketFeed(symbol="BTCUSDT")
        self.public_client = self.feed.client

    async def get_market_state(self, symbol: str) -> MarketState:
        return await self.feed.refresh()

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        try:
            raw = await self.public_client.get_orderbook(symbol, limit=limit)
            norm = BinanceUSDMFuturesPublicClient.normalize_orderbook(raw)
            book = OrderBook(symbol=symbol, exchange="BINANCE")
            book.apply_snapshot(norm["sequence"], norm["bids"], norm["asks"], now=datetime.now(UTC))
            return book
        except BinancePublicDataUnavailable:
            # Fall back to simulated book only for execution/paper continuity.
            return await super().get_orderbook(symbol, limit=limit)

    async def refresh_market_state(self, symbol: str) -> MarketState:
        state = await self.feed.refresh()
        # keep simulated book aligned to the real mid so paper fills reflect real levels
        if state.best_bid > 0 and state.best_ask > 0:
            book = OrderBook(symbol=symbol, exchange="BINANCE")
            book.apply_snapshot(
                int(datetime.now(UTC).timestamp()),
                [(state.best_bid, Decimal("1"))],
                [(state.best_ask, Decimal("1"))],
            )
            self.books[symbol] = book
            self.sequence[symbol] = book.sequence or 0
        return state
