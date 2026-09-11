"""PAPER_REAL_MARKET adapter: real public OKX data + simulated execution."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.errors import MarketDataUnhealthy, OrderRejected
from crypto_trader.domain.models import Instrument, Order
from crypto_trader.domain.money import D
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.orderbook import OrderBook
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

    @staticmethod
    def _factual_size(symbol: str, side: str, value: Decimal | None) -> Decimal:
        size = value or Decimal("0")
        if size <= 0:
            raise MarketDataUnhealthy(
                f"OKX factual {side} size unavailable for {symbol}"
            )
        return size

    async def get_market_state(self, symbol: str) -> MarketState:
        return await self.feed.refresh(symbol)

    async def get_exchange_info(self, symbol: str | None = None) -> list[Instrument]:
        """Load factual executable OKX USDT linear-SWAP instruments.

        With ``symbol=None`` this returns the full execution registry, not only
        the bounded feed symbol. Non-linear / non-USDT products are not claimed
        executable by this PAPER runtime.
        """

        try:
            rows = await self.feed.client.get_instruments("SWAP")
        except Exception:
            return []
        parsed: list[Instrument] = []
        for raw in rows:
            inst_id = raw.get("instId", "")
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            if raw.get("state") != "live":
                continue
            if raw.get("ctType") != "linear":
                continue
            instrument = self._instrument_from_okx_row(raw)
            if instrument is None:
                continue
            parsed.append(instrument)
        if symbol is None:
            for instrument in parsed:
                self.instruments[instrument.symbol] = instrument
            return parsed
        canonical = symbol.upper()
        for instrument in parsed:
            if instrument.symbol == canonical:
                self.instruments[canonical] = instrument
                return [instrument]
        return []

    def _instrument_from_okx_row(self, raw: dict) -> Instrument | None:
        """Build only a fully proven LINEAR_PERP executable instrument.

        Missing/empty/malformed ctVal, ctMult or ctType never becomes a
        default; the row is excluded instead.
        """
        inst_id = str(raw.get("instId") or "")
        try:
            canonical = SymbolMapper().to_canonical(inst_id)
        except ValueError:
            return None
        inst_type = str(raw.get("instType") or "")
        ct_type = str(raw.get("ctType") or "")
        if inst_type != "SWAP" or ct_type != "linear":
            return None
        if str(raw.get("state") or "") != "live":
            return None
        tick_size = _positive_decimal(raw.get("tickSz"))
        lot_size = _positive_decimal(raw.get("lotSz"))
        min_size = _positive_decimal(raw.get("minSz"))
        contract_size = _positive_decimal(raw.get("ctVal"))
        contract_multiplier = _positive_decimal(raw.get("ctMult"))
        if any(
            value is None
            for value in (
                tick_size,
                lot_size,
                min_size,
                contract_size,
                contract_multiplier,
            )
        ):
            return None
        base, quote, *_ = inst_id.split("-")
        return Instrument(
            symbol=canonical,
            base_asset=base,
            quote_asset=quote,
            status="TRADING",
            tick_size=tick_size,
            step_size=lot_size,
            min_qty=min_size,
            min_notional=Decimal("0.00000001"),
            price_precision=_precision(tick_size),
            quantity_precision=_precision(lot_size),
            exchange="OKX",
            instrument_type="LINEAR_PERP",
            contract_size=contract_size,
            contract_multiplier=contract_multiplier,
            inst_id=inst_id,
            inst_type=inst_type,
            ct_type=ct_type,
            ct_val=str(raw.get("ctVal")),
            ct_mult=str(raw.get("ctMult")),
            ct_val_ccy=raw.get("ctValCcy"),
            settle_ccy=raw.get("settleCcy"),
            state="live",
            list_time=raw.get("listTime"),
            expiry_time=raw.get("expTime"),
            lot_size=str(raw.get("lotSz")),
            min_size=str(raw.get("minSz")),
        )

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        try:
            state = await self.feed.refresh(symbol)
            if state.health.value != "HEALTHY":
                raise MarketDataUnhealthy(f"OKX public market unavailable for {symbol}")
            if state.best_bid <= 0 or state.best_ask <= 0:
                raise MarketDataUnhealthy(f"OKX factual price unavailable for {symbol}")
            bid_size = self._factual_size(symbol, "bid", state.best_bid_size)
            ask_size = self._factual_size(symbol, "ask", state.best_ask_size)
            book = OrderBook(symbol=symbol, exchange="OKX")
            book.apply_snapshot(
                int(datetime.now(UTC).timestamp() * 1000),
                [(state.best_bid, bid_size)],
                [(state.best_ask, ask_size)],
                now=datetime.now(UTC),
            )
            return book
        except MarketDataUnhealthy:
            raise
        except Exception as exc:
            raise MarketDataUnhealthy(f"OKX public market unavailable for {symbol}: {exc}") from exc

    async def refresh_market_state(self, symbol: str) -> MarketState:
        state = await self.feed.refresh(symbol)
        if state.health.value != "HEALTHY":
            raise MarketDataUnhealthy(f"OKX public market unavailable for {symbol}")
        if state.best_bid <= 0 or state.best_ask <= 0:
            raise MarketDataUnhealthy(f"OKX factual price unavailable for {symbol}")
        bid_size = self._factual_size(symbol, "bid", state.best_bid_size)
        ask_size = self._factual_size(symbol, "ask", state.best_ask_size)
        # keep simulated book aligned to the real book so paper fills reflect
        # factual OKX levels only; never seed a synthetic book here.
        book = OrderBook(symbol=symbol, exchange="OKX")
        book.apply_snapshot(
            int(datetime.now(UTC).timestamp()),
            [(state.best_bid, bid_size)],
            [(state.best_ask, ask_size)],
        )
        self.books[symbol] = book
        self.sequence[symbol] = book.sequence or 0
        return state

    async def submit_order(self, order: Order) -> Order:
        """Reject PAPER_REAL_MARKET orders without a factual same-symbol book."""
        book = self.books.get(order.symbol)
        if book is None or book.best_bid() is None or book.best_ask() is None:
            raise OrderRejected("MARKET_DATA_UNAVAILABLE")
        return await super().submit_order(order)

    async def disconnect(self) -> None:
        await self.feed.close()
        await super().disconnect()


def _positive_decimal(value) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = D(text)
    except Exception:
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _precision(step: Decimal) -> int:
    return max(0, -step.normalize().as_tuple().exponent)
