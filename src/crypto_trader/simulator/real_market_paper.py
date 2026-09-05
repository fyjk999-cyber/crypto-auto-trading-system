"""PAPER_REAL_MARKET adapter: real public OKX data + simulated execution."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.errors import MarketDataUnhealthy
from crypto_trader.domain.models import Instrument
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

    async def get_market_state(self, symbol: str) -> MarketState:
        return await self.feed.refresh(symbol)

    async def get_exchange_info(self, symbol: str | None = None) -> list[Instrument]:
        """Load the bounded execution symbol's factual OKX linear-SWAP contract."""

        canonical = (symbol or self.feed.symbol).upper()
        provider_symbol = SymbolMapper().to_okx(canonical)
        try:
            rows = await self.feed.client.get_instruments("SWAP")
        except Exception:
            return []
        matches = [
            row
            for row in rows
            if row.get("instId") == provider_symbol
            and row.get("state") == "live"
            and row.get("ctType", "linear") == "linear"
        ]
        if len(matches) != 1:
            return []
        raw = matches[0]
        tick_size = D(raw.get("tickSz", "0"))
        lot_size = D(raw.get("lotSz", "0"))
        min_size = D(raw.get("minSz", "0"))
        contract_size = D(raw.get("ctVal", "0"))
        contract_multiplier = D(raw.get("ctMult") or "1")
        if min(tick_size, lot_size, min_size, contract_size, contract_multiplier) <= 0:
            return []
        base, quote, *_ = provider_symbol.split("-")
        instrument = Instrument(
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
            )
        self.instruments[canonical] = instrument
        return [instrument]

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        try:
            state = await self.feed.refresh(symbol)
            if state.health.value != "HEALTHY":
                raise MarketDataUnhealthy(f"OKX public market unavailable for {symbol}")
            book = OrderBook(symbol=symbol, exchange="OKX")
            book.apply_snapshot(
                int(datetime.now(UTC).timestamp() * 1000),
                [(state.best_bid, Decimal("1"))],
                [(state.best_ask, Decimal("1"))],
                now=datetime.now(UTC),
            )
            return book
        except Exception as exc:
            raise MarketDataUnhealthy(f"OKX public market unavailable for {symbol}: {exc}") from exc

    async def refresh_market_state(self, symbol: str) -> MarketState:
        state = await self.feed.refresh(symbol)
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

    async def disconnect(self) -> None:
        await self.feed.close()
        await super().disconnect()


def _precision(step: Decimal) -> int:
    return max(0, -step.normalize().as_tuple().exponent)
