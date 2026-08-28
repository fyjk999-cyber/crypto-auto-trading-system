"""PAPER_REAL_MARKET adapter: real public OKX data + simulated execution."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.errors import MarketDataUnhealthy
from crypto_trader.domain.money import D
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.state import MarketState
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

logger = logging.getLogger(__name__)


class PaperRealMarketAdapter(SimulatedExchangeAdapter):
    """Real public market data; paper fills via the simulated exchange."""

    def __init__(
        self,
        *,
        initial_balances=None,
        instruments=None,
        feed: OKXPublicMarketFeed | None = None,
        feed_factory: Callable[[str], OKXPublicMarketFeed] | None = None,
    ) -> None:
        super().__init__(initial_balances=initial_balances, instruments=instruments)
        self.mapper = SymbolMapper()
        self._feed_factory = feed_factory or (lambda symbol: OKXPublicMarketFeed(symbol=symbol))
        primary_symbol = instruments[0].symbol if instruments else "BTCUSDT"
        primary_feed = feed or self._feed_factory(primary_symbol)
        self._feeds: dict[str, OKXPublicMarketFeed] = {primary_feed.symbol: primary_feed}
        # Compatibility attributes retained for existing diagnostics/tests.
        self.feed = primary_feed
        self.public_client = primary_feed.client

    def _feed_for(self, symbol: str) -> OKXPublicMarketFeed:
        canonical = self.mapper.to_canonical(symbol)
        current = self._feeds.get(canonical)
        if current is None:
            current = self._feed_factory(canonical)
            self._feeds[canonical] = current
        return current

    async def get_market_state(self, symbol: str) -> MarketState:
        return await self._feed_for(symbol).refresh()

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        try:
            canonical = self.mapper.to_canonical(symbol)
            provider_symbol = self.mapper.to_okx(canonical)
            feed = self._feed_for(canonical)
            raw = await feed.client.get_orderbook(provider_symbol, limit=limit)
            payload = raw["data"][0]
            bids = [(D(row[0]), D(row[1])) for row in payload.get("bids", [])]
            asks = [(D(row[0]), D(row[1])) for row in payload.get("asks", [])]
            book = OrderBook(symbol=canonical, exchange="OKX")
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
        canonical = self.mapper.to_canonical(symbol)
        state = await self._feed_for(canonical).refresh()
        # Keep simulated book aligned to the real mid so paper fills reflect real levels.
        if state.best_bid > 0 and state.best_ask > 0:
            book = OrderBook(symbol=canonical, exchange="OKX")
            book.apply_snapshot(
                int(datetime.now(UTC).timestamp()),
                [(state.best_bid, Decimal("1"))],
                [(state.best_ask, Decimal("1"))],
            )
            self.books[canonical] = book
            self.sequence[canonical] = book.sequence or 0
        return state

    async def submit_order(self, order):
        """Real-price PAPER execution.

        CRITICAL price-integrity rule (no fake fills): the simulated matcher
        must never fall back to its seeded synthetic book (mid=100). Before
        matching, refresh this adapter's book for the order symbol from the
        REAL OKX public feed. If the real reference price is unavailable the
        submission fails closed -- no fill at a fabricated level.
        """
        from crypto_trader.domain.errors import ExchangeError

        try:
            canonical = self.mapper.to_canonical(order.symbol)
            state = await self.refresh_market_state(canonical)
        except Exception as exc:
            raise ExchangeError(
                f"REAL_REFERENCE_PRICE_UNAVAILABLE for {order.symbol}: "
                f"{type(exc).__name__}"
            ) from exc
        if state is None or state.best_bid <= 0 or state.best_ask <= 0:
            raise ExchangeError(
                f"REAL_REFERENCE_PRICE_UNAVAILABLE for {order.symbol}"
            )
        return await super().submit_order(order)

    async def disconnect(self) -> None:
        closed_clients: set[int] = set()
        for feed in self._feeds.values():
            client_id = id(feed.client)
            if client_id in closed_clients:
                continue
            closed_clients.add(client_id)
            try:
                await feed.close()
            except Exception as exc:
                logger.debug(
                    "OKX public feed close failed symbol=%s error=%s",
                    feed.symbol,
                    type(exc).__name__,
                )
        await super().disconnect()
