"""PAPER_REAL_MARKET adapter: real public OKX data + simulated execution."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.errors import MarketDataUnhealthy
from crypto_trader.domain.money import D
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.state import MarketState
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter


class PaperRealMarketAdapter(SimulatedExchangeAdapter):
    """Real public market data; paper fills via the simulated exchange."""

    def __init__(
        self,
        *,
        initial_balances=None,
        instruments=None,
        feed: OKXPublicMarketFeed | None = None,
    ) -> None:
        super().__init__(initial_balances=initial_balances, instruments=instruments)
        self.feed = feed or OKXPublicMarketFeed(symbol="BTCUSDT")
        self.public_client = self.feed.client

    async def get_market_state(self, symbol: str) -> MarketState:
        return await self.feed.refresh()

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        try:
            provider_symbol = SymbolMapper().to_okx(symbol)
            raw = await self.public_client.get_orderbook(provider_symbol, limit=limit)
            payload = raw["data"][0]
            bids = [(D(row[0]), D(row[1])) for row in payload.get("bids", [])]
            asks = [(D(row[0]), D(row[1])) for row in payload.get("asks", [])]
            book = OrderBook(symbol=symbol, exchange="OKX")
            book.apply_snapshot(
                int(payload.get("ts", "0")), bids, asks, now=datetime.now(UTC)
            )
            return book
        except Exception as exc:
            # NO silent synthetic fallback in PAPER_REAL_MARKET.
            raise MarketDataUnhealthy(
                f"OKX public market unavailable for {symbol}: {exc}"
            ) from exc

    async def refresh_market_state(self, symbol: str) -> MarketState:
        state = await self.feed.refresh()
        # keep simulated book aligned to the real mid so paper fills reflect real levels
        if state.best_bid > 0 and state.best_ask > 0:
            book = OrderBook(symbol=symbol, exchange="OKX")
            book.apply_snapshot(
                int(datetime.now(UTC).timestamp()),
                [(state.best_bid, Decimal("1"))],
                [(state.best_ask, Decimal("1"))],
            )
            self.books[symbol] = book
            self.sequence[symbol] = book.sequence or 0
        return state
