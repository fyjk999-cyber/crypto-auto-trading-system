"""Keyless factual OKX public market state for PAPER execution."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.domain.money import D
from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.state import DataHealth, MarketState, SourceStatus

# OKX bar identifiers are case-sensitive: hourly bars require an uppercase H.
OKX_BAR_MAP = {"1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H"}


class OKXPublicMarketFeed:
    """Bounded per-symbol REST polling; failed fields stay explicitly unavailable."""

    source = "OKX_PUBLIC"

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        *,
        client: OKXAdapter | None = None,
        min_refresh_interval_seconds: float = 1.0,
        max_cached_symbols: int = 128,
        trades_limit: int = 100,
        trades_max_window_seconds: float = 300.0,
        large_trade_notional_usd: Decimal = Decimal("100000"),
    ) -> None:
        self.symbol = symbol
        self.client = client or OKXAdapter(demo=False)
        self.states: dict[str, MarketState] = {}
        self._oi_previous: dict[str, Decimal] = {}
        self._price_history: dict[str, deque[Decimal]] = {}
        self._trades: dict[str, deque[tuple[int, str, str, Decimal, Decimal]]] = {}
        self._candle_cache: dict[tuple[str, str, int], tuple[float, list]] = {}
        self._last_access: dict[str, float] = {}
        self.max_cached_symbols = max(1, int(max_cached_symbols))
        self.trades_limit = max(1, int(trades_limit))
        self.trades_max_window_seconds = max(1.0, float(trades_max_window_seconds))
        self.large_trade_notional_usd = Decimal(large_trade_notional_usd)
        self.warmup_status = "NOT_ATTEMPTED"
        self.warmup_loaded = 0
        self.warmup_error: str | None = None
        self.min_refresh_interval = timedelta(seconds=max(0.0, min_refresh_interval_seconds))

    def provider_symbol(self, symbol: str) -> str:
        return SymbolMapper().to_okx(symbol)

    def _evict_if_needed(self, protected: str | None = None) -> None:
        """Bound the multi-symbol cache; never evict the pinned execution symbol."""
        pinned = {self.symbol, protected} - {None}
        while len(self.states) >= self.max_cached_symbols:
            candidates = [s for s in self.states if s not in pinned]
            if not candidates:
                return
            oldest = min(candidates, key=lambda s: self._last_access.get(s, 0.0))
            self.states.pop(oldest, None)
            self._trades.pop(oldest, None)
            self._oi_previous.pop(oldest, None)
            self._price_history.pop(oldest, None)
            self._last_access.pop(oldest, None)
            for cache_key in [item for item in self._candle_cache if item[0] == oldest]:
                self._candle_cache.pop(cache_key, None)

    def _state(self, symbol: str) -> MarketState:
        if symbol not in self.states:
            self._evict_if_needed(protected=symbol)
        self._last_access[symbol] = datetime.now(UTC).timestamp()
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

    async def warmup(
        self,
        mde: MarketDataEngine,
        symbol: str | None = None,
        *,
        bars: int = 300,
        interval: str = "1m",
    ) -> int:
        """Seed quant history from factual, closed OKX candles only.

        Warm-up is evidence preparation, not a market fallback. Provider
        failure leaves the engine empty (or preserves its existing bars) and
        is reported without returning provider exception text.
        """

        symbol = symbol or self.symbol
        try:
            raw = await self.client.get_candles(self.provider_symbol(symbol), interval, bars)
            closed: dict[int, list] = {}
            for row in raw:
                if not isinstance(row, list) or len(row) < 9 or str(row[8]) != "1":
                    continue
                closed[int(row[0])] = row

            latest = mde.latest()
            latest_ms = int(latest.ts.timestamp() * 1000) if latest else -1
            loaded = 0
            for timestamp_ms, row in sorted(closed.items()):
                if timestamp_ms <= latest_ms:
                    continue
                mde.ingest(
                    datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
                    D(row[4]),
                    D(row[5]),
                )
                loaded += 1

            self.warmup_loaded = loaded
            self.warmup_status = "HEALTHY" if loaded else "UNAVAILABLE"
            self.warmup_error = None
            return loaded
        except Exception as exc:
            self.warmup_loaded = 0
            self.warmup_status = "UNAVAILABLE"
            self.warmup_error = type(exc).__name__
            return 0

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
        if existing is not None and now - existing.received_timestamp < self.min_refresh_interval:
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
        await self._refresh_trades(state, provider_symbol, now)

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
            self._update_realized_volatility(state)
            state.trade_volume = D(ticker.get("volume_24h", "0"))
            state.volume = state.trade_volume
            state.exchange_timestamp = _timestamp(ticker.get("source_timestamp"), now)
            self._status(state, "ticker", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.price = Decimal("0")
            state.trade_volume = Decimal("0")
            state.volume = Decimal("0")
            self._status(state, "ticker", now, DataHealth.UNAVAILABLE, exc)

    def _update_realized_volatility(self, state: MarketState) -> None:
        prices = self._price_history.setdefault(state.symbol, deque(maxlen=61))
        prices.append(state.price)
        if len(prices) < 3:
            state.realized_volatility = None
            return
        observations = list(prices)
        returns = [
            current / previous - Decimal("1")
            for previous, current in zip(observations, observations[1:], strict=False)
            if previous > 0
        ]
        if len(returns) < 2:
            state.realized_volatility = None
            return
        mean = sum(returns, Decimal("0")) / Decimal(len(returns))
        variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(
            len(returns)
        )
        state.realized_volatility = variance.sqrt()

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
            state.bid_size, state.ask_size = bid.quantity, ask.quantity
            total = bid.quantity + ask.quantity
            state.imbalance_l1 = (
                (bid.quantity - ask.quantity) / total if total > 0 else Decimal("0")
            )
            state.spread = ask.price - bid.price
            state.depth = sum((level.quantity for level in book.bids.values()), Decimal("0")) + sum(
                (level.quantity for level in book.asks.values()), Decimal("0")
            )
            _apply_book_microstructure(state, book)
            self._status(state, "orderbook", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.best_bid = Decimal("0")
            state.best_ask = Decimal("0")
            state.bid_size = Decimal("0")
            state.ask_size = Decimal("0")
            state.imbalance_l1 = Decimal("0")
            state.spread = Decimal("0")
            state.depth = Decimal("0")
            state.depth_bid_5 = Decimal("0")
            state.depth_ask_5 = Decimal("0")
            state.depth_bid_10 = Decimal("0")
            state.depth_ask_10 = Decimal("0")
            state.imbalance_l5 = Decimal("0")
            state.microprice = Decimal("0")
            state.spread_bps = Decimal("0")
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

    async def _refresh_trades(self, state: MarketState, symbol: str, now: datetime) -> None:
        """Bounded factual public-trade window → taker flow / CVD facts."""
        try:
            rows = await self.client.get_trades(symbol, self.trades_limit)
            window = self._trades.setdefault(state.symbol, deque(maxlen=self.trades_limit))
            known = {entry[1] for entry in window}
            parsed: list[tuple[int, str, str, Decimal, Decimal]] = []
            for raw in rows:
                trade_id = str(raw.get("tradeId") or "")
                if not trade_id or trade_id in known:
                    continue
                side = str(raw.get("side") or "").lower()
                if side not in ("buy", "sell"):
                    continue
                try:
                    price = D(raw.get("px"))
                    size = D(raw.get("sz"))
                    ts_ms = int(raw.get("ts") or 0)
                except Exception:
                    continue
                if price <= 0 or size <= 0 or ts_ms <= 0:
                    continue
                parsed.append((ts_ms, trade_id, side, price, size))
            # Newest first from the provider; keep window ascending by time.
            parsed.sort(key=lambda entry: entry[0])
            for entry in parsed:
                window.append(entry)
            cutoff_ms = int(now.timestamp() * 1000) - int(self.trades_max_window_seconds * 1000)
            live = [entry for entry in window if entry[0] >= cutoff_ms]
            if not live:
                raise ValueError("no factual trades inside the bounded window")
            buy_volume = sum((e[4] for e in live if e[2] == "buy"), Decimal("0"))
            sell_volume = sum((e[4] for e in live if e[2] == "sell"), Decimal("0"))
            notionals = [e[3] * e[4] for e in live]
            largest = max(notionals)
            state.taker_buy_volume = buy_volume
            state.taker_sell_volume = sell_volume
            state.cvd = buy_volume - sell_volume
            state.trade_count = len(live)
            state.trade_notional = sum(notionals, Decimal("0"))
            state.large_trade_count = sum(
                1 for value in notionals if value >= self.large_trade_notional_usd
            )
            state.largest_trade_notional = largest
            state.trades_window_seconds = max(0.0, (live[-1][0] - live[0][0]) / 1000.0)
            state.last_trade_price = live[-1][3]
            self._status(state, "trades", now, DataHealth.HEALTHY)
        except Exception as exc:
            state.taker_buy_volume = None
            state.taker_sell_volume = None
            state.cvd = None
            state.trade_count = 0
            state.trade_notional = None
            state.large_trade_count = 0
            state.largest_trade_notional = None
            state.trades_window_seconds = 0.0
            state.last_trade_price = None
            self._status(state, "trades", now, DataHealth.UNAVAILABLE, exc)

    async def get_closed_candles(
        self,
        symbol: str,
        *,
        bar: str = "1m",
        limit: int = 300,
        max_age_seconds: float = 60.0,
    ):
        """Bounded per-symbol cache of factual CLOSED candles (keyless public API).

        Only rows with OKX's closed flag (``confirm == "1"``) are returned; live
        candles are never mixed into model history. Failures return the last
        cached factual history (explicitly stale) or an empty list — never a
        synthetic substitute.
        """
        from crypto_trader.market_data.opportunity.factors import Candle

        cache = self._candle_cache
        key = (symbol, OKX_BAR_MAP.get(bar, bar), int(limit))
        now_ts = datetime.now(UTC).timestamp()
        entry = cache.get(key)
        if entry is not None and (now_ts - entry[0]) <= max_age_seconds:
            return list(entry[1])
        provider_bar = OKX_BAR_MAP.get(bar, bar)
        try:
            rows = await self.client.get_candles(self.provider_symbol(symbol), provider_bar, limit)
        except Exception:
            if entry is not None:
                return list(entry[1])
            return []
        candles: list[Candle] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 9 or str(row[8]) != "1":
                continue
            try:
                candles.append(
                    Candle(
                        ts_ms=int(row[0]),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )
            except (TypeError, ValueError):
                continue
        candles.sort(key=lambda item: item.ts_ms)
        if candles:
            if len(cache) >= self.max_cached_symbols and key not in cache:
                oldest_keys = sorted(cache, key=lambda item: cache[item][0])
                for victim in oldest_keys:
                    if victim[0] != self.symbol:
                        cache.pop(victim, None)
                        break
            cache[key] = (now_ts, candles)
        return list(candles)

    async def close(self) -> None:
        await self.client.disconnect()


def _apply_book_microstructure(state: MarketState, book: OrderBook) -> None:
    """Derive L5/L10 depth, imbalance, microprice and spread bps facts only."""
    bid_levels = sorted(book.bids.values(), key=lambda level: level.price, reverse=True)
    ask_levels = sorted(book.asks.values(), key=lambda level: level.price)
    state.depth_bid_5 = sum((level.quantity for level in bid_levels[:5]), Decimal("0"))
    state.depth_ask_5 = sum((level.quantity for level in ask_levels[:5]), Decimal("0"))
    state.depth_bid_10 = sum((level.quantity for level in bid_levels[:10]), Decimal("0"))
    state.depth_ask_10 = sum((level.quantity for level in ask_levels[:10]), Decimal("0"))
    total_5 = state.depth_bid_5 + state.depth_ask_5
    state.imbalance_l5 = (
        (state.depth_bid_5 - state.depth_ask_5) / total_5 if total_5 > 0 else Decimal("0")
    )
    if bid_levels and ask_levels:
        best_bid, best_ask = bid_levels[0], ask_levels[0]
        top = best_bid.quantity + best_ask.quantity
        if top > 0:
            state.microprice = (
                best_ask.price * best_bid.quantity + best_bid.price * best_ask.quantity
            ) / top
    mid = (state.best_bid + state.best_ask) / Decimal("2")
    state.spread_bps = (
        (state.best_ask - state.best_bid) / mid * Decimal("10000") if mid > 0 else Decimal("0")
    )


def _positive(value, field: str) -> Decimal:
    parsed = D(value or "0")
    if parsed <= 0:
        raise ValueError(f"OKX {field} is not positive")
    return parsed


def _timestamp(value, fallback: datetime) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC) if value else fallback
