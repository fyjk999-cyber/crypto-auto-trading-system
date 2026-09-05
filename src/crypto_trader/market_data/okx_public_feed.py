"""Keyless factual OKX public market state for PAPER execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.state import DataHealth, MarketState, SourceStatus


class OKXPublicMarketFeed:
    """Bounded per-symbol REST polling; failed fields stay explicitly unavailable."""

    source = "OKX_PUBLIC"

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        *,
        client: OKXAdapter | None = None,
        min_refresh_interval_seconds: float = 1.0,
    ) -> None:
        self.symbol = symbol
        self.client = client or OKXAdapter(demo=False)
        self.states: dict[str, MarketState] = {}
        self._oi_previous: dict[str, Decimal] = {}
        self.min_refresh_interval = timedelta(
            seconds=max(0.0, min_refresh_interval_seconds)
        )

    def provider_symbol(self, symbol: str) -> str:
        return SymbolMapper().to_okx(symbol)

    def _state(self, symbol: str) -> MarketState:
        return self.states.setdefault(
            symbol,
            MarketState(
                symbol=symbol,
                provider=self.source,
                data_source="REAL",
                instrument_id=self.provider_symbol(symbol),
                instrument_type="SWAP",
                source=self.source,
                exchange="OKX",
            ),
        )

    def _status(
        self,
        state: MarketState,
        name: str,
        now: datetime,
        health: DataHealth,
        error: Exception | None = None,
    ) -> None:
        state.sources[name] = SourceStatus(
            source=self.source,
            data_source=self.source,
            status=health,
            age_seconds=0 if health == DataHealth.HEALTHY else -1,
            updated_at=now,
            last_error=str(error)[:256] if error else None,
        )

    async def refresh(self, symbol: str | None = None) -> MarketState:
        symbol = symbol or self.symbol
        provider_symbol = self.provider_symbol(symbol)
        now = datetime.now(UTC)
        existing = self.states.get(symbol)
        if (
            existing is not None
            and now - existing.received_timestamp < self.min_refresh_interval
        ):
            self._update_source_ages(existing, now)
            return existing
        state = self._state(symbol)
        # A generation is a completed factual provider observation attempt.
        # Without it the new-risk gate must (correctly) reject all entries.
        state.generation += 1

        await self._refresh_ticker(state, provider_symbol, now)
        await self._refresh_book(state, provider_symbol, now)
        await self._refresh_mark(state, provider_symbol, now)
        await self._refresh_index(state, provider_symbol, now)
        await self._refresh_funding(state, provider_symbol, now)
        await self._refresh_oi(state, provider_symbol, now)

        state.received_timestamp = now
        state.timestamp = now
        state.compute_basis()
        state.mark_healthy_from_sources()
        ticker_health = state.sources.get("ticker", SourceStatus()).status
        book_health = state.sources.get("orderbook", SourceStatus()).status
        if ticker_health != DataHealth.HEALTHY or book_health != DataHealth.HEALTHY:
            state.health = DataHealth.UNAVAILABLE
            state.freshness = DataHealth.UNAVAILABLE
            state.status = DataHealth.UNAVAILABLE
            state.new_risk_allowed = False
            state.new_risk_block_reason = "CORE_OKX_MARKET_UNAVAILABLE"
        return state

    @staticmethod
    def _update_source_ages(state: MarketState, now: datetime) -> None:
        for source in state.sources.values():
            if source.updated_at is not None:
                source.age_seconds = max(0.0, (now - source.updated_at).total_seconds())

    async def _refresh_ticker(self, state: MarketState, symbol: str, now: datetime) -> None:
        try:
            ticker = await self.client.get_ticker(symbol)
            state.price = _positive(ticker.get("last"), "last price")
            state.trade_volume = D(ticker.get("volume_24h", "0"))
            state.volume = state.trade_volume
            state.exchange_timestamp = _timestamp(ticker.get("source_timestamp"), now)
            self._status(state, "ticker", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.price = Decimal("0")
            state.trade_volume = Decimal("0")
            state.volume = Decimal("0")
            self._status(state, "ticker", now, DataHealth.UNAVAILABLE, exc)

    async def _refresh_book(self, state: MarketState, symbol: str, now: datetime) -> None:
        try:
            payload = await self.client.get_orderbook(symbol)
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                raise ValueError("OKX orderbook response is empty")
            raw = rows[0]
            book = OrderBook(symbol=state.symbol, exchange="OKX")
            book.apply_snapshot(
                int(raw.get("ts", "0")),
                [(D(level[0]), D(level[1])) for level in raw.get("bids", [])],
                [(D(level[0]), D(level[1])) for level in raw.get("asks", [])],
                now=now,
            )
            bid, ask = book.best_bid(), book.best_ask()
            if bid is None or ask is None:
                raise ValueError("OKX orderbook has no bid or ask")
            state.best_bid, state.best_ask = bid.price, ask.price
            state.spread = ask.price - bid.price
            state.depth = sum((level.quantity for level in book.bids.values()), Decimal("0")) + sum(
                (level.quantity for level in book.asks.values()), Decimal("0")
            )
            self._status(state, "orderbook", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.best_bid = Decimal("0")
            state.best_ask = Decimal("0")
            state.spread = Decimal("0")
            state.depth = Decimal("0")
            self._status(state, "orderbook", now, DataHealth.UNAVAILABLE, exc)

    async def _refresh_mark(self, state: MarketState, symbol: str, now: datetime) -> None:
        try:
            value = await self.client.get_mark_price(symbol)
            state.mark_price = _positive(value.get("mark_price"), "mark price")
            self._status(state, "mark_price", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.mark_price = Decimal("0")
            self._status(state, "mark_price", now, DataHealth.UNAVAILABLE, exc)

    async def _refresh_index(self, state: MarketState, symbol: str, now: datetime) -> None:
        try:
            value = await self.client.get_index_price(symbol)
            state.index_price = _positive(value.get("index_price"), "index price")
            self._status(state, "index_price", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.index_price = Decimal("0")
            self._status(state, "index_price", now, DataHealth.UNAVAILABLE, exc)

    async def _refresh_funding(self, state: MarketState, symbol: str, now: datetime) -> None:
        try:
            value = await self.client.get_funding_rate(symbol)
            state.funding_rate = D(value.get("funding_rate", "0"))
            state.next_funding_time = value.get("next_funding_time")
            self._status(state, "funding", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.funding_rate = None
            state.next_funding_time = None
            self._status(state, "funding", now, DataHealth.UNAVAILABLE, exc)

    async def _refresh_oi(self, state: MarketState, symbol: str, now: datetime) -> None:
        try:
            value = await self.client.get_open_interest(symbol)
            current = _positive(value.get("open_interest"), "open interest")
            previous = self._oi_previous.get(state.symbol)
            state.open_interest = current
            state.open_interest_change = current - previous if previous is not None else None
            self._oi_previous[state.symbol] = current
            self._status(state, "open_interest", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.open_interest = None
            state.open_interest_change = None
            self._status(state, "open_interest", now, DataHealth.UNAVAILABLE, exc)

    async def close(self) -> None:
        await self.client.disconnect()


def _positive(value, field: str) -> Decimal:
    parsed = D(value or "0")
    if parsed <= 0:
        raise ValueError(f"OKX {field} is not positive")
    return parsed


def _timestamp(value, fallback: datetime) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC) if value else fallback
