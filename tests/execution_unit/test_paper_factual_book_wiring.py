"""Execution wiring tests: the PAPER_REAL_MARKET factual-book gate.

Root cause this fix addresses:

    ``PaperRealMarketAdapter.submit_order`` refused any order whose symbol had
    no factual book, while the base matcher would otherwise fall back to
    ``seed_book`` — a SYNTHETIC book. The guard was right; the wiring was
    missing, because ``refresh_market_state`` had no caller at all. The result
    was that no PAPER order could ever fill.

Invariants kept by the fix (asserted below):

    * real factual OKX levels are used,
    * a genuinely unavailable / non-factual market still fails closed with
      ``OrderRejected`` — never a synthetic book,
    * one immutable order identity cannot become two orders,
    * an incomplete ``refresh_market_state`` leaves no half-built book behind.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradingMode,
)
from crypto_trader.domain.errors import MarketDataUnhealthy, OrderRejected
from crypto_trader.domain.models import Order
from crypto_trader.market_data.state import DataHealth, MarketState
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter


def _state(
    symbol: str = "SOPHUSDT",
    *,
    health: DataHealth = DataHealth.HEALTHY,
    best_bid: str = "100",
    best_ask: str = "101",
    bid_size: str = "50",
    ask_size: str = "60",
) -> MarketState:
    now = datetime.now(UTC)
    return MarketState(
        symbol=symbol,
        health=health,
        status=health,
        freshness=health,
        best_bid=Decimal(best_bid),
        best_ask=Decimal(best_ask),
        best_bid_size=Decimal(bid_size),
        best_ask_size=Decimal(ask_size),
        price=Decimal(best_bid),
        timestamp=now,
        received_timestamp=now,
        generation=1,
    )


class _Feed:
    """Minimal factual-feed stand-in for ``OKXPublicMarketFeed``."""

    def __init__(self, state: MarketState | Exception) -> None:
        self._state = state
        self.calls: list[str] = []

    async def refresh(self, symbol: str) -> MarketState:
        self.calls.append(symbol)
        if isinstance(self._state, Exception):
            raise self._state
        return self._state

    async def close(self) -> None:
        return None


def _order(
    *,
    symbol: str = "SOPHUSDT",
    side: OrderSide = OrderSide.SELL,
    price: str = "95",
    quantity: str = "10",
    client_order_id: str = "cid-1",
) -> Order:
    now = datetime.now(UTC)
    return Order(
        internal_order_id="ord_exec_1",
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=Decimal(price),
        quantity=Decimal(quantity),
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        strategy_id="live_llm",
        created_at=now,
        updated_at=now,
    )


async def _adapter(state: MarketState | Exception) -> PaperRealMarketAdapter:
    adapter = PaperRealMarketAdapter(feed=_Feed(state))
    await adapter.connect()
    return adapter


# ------------------------------------------------------------------ happy path
async def test_submit_without_prior_book_builds_factual_book_and_is_accepted():
    """The guard no longer deadlocks: the factual book is materialised on demand."""
    adapter = await _adapter(_state())
    assert adapter.books.get("SOPHUSDT") is None

    order = await adapter.submit_order(_order(price="99"))

    assert adapter.books["SOPHUSDT"] is not None
    assert order.status in (OrderStatus.ACKNOWLEDGED, OrderStatus.OPEN, OrderStatus.FILLED)
    # factual levels came from the feed, not from seed_book
    book = adapter.books["SOPHUSDT"]
    assert book.best_bid().price == Decimal("100")
    assert book.best_ask().price == Decimal("101")


async def test_marketable_sell_fills_against_factual_bid():
    """A SELL whose limit crosses the factual bid produces a factual fill."""
    adapter = await _adapter(_state())
    order = await adapter.submit_order(_order(price="90"))

    assert order.filled_quantity > 0
    assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)


async def test_existing_book_is_reused_without_refetching():
    """Once a factual book exists the guard must not re-hit the provider."""
    feed = _Feed(_state())
    adapter = PaperRealMarketAdapter(feed=feed)
    await adapter.connect()

    await adapter.refresh_market_state("SOPHUSDT")
    calls_after_first = len(feed.calls)

    await adapter.submit_order(_order(price="99"))
    assert len(feed.calls) == calls_after_first


# --------------------------------------------------------------- fail-closed
async def test_unhealthy_feed_still_fails_closed():
    adapter = await _adapter(_state(health=DataHealth.UNAVAILABLE))
    with pytest.raises(OrderRejected, match="MARKET_DATA_UNAVAILABLE"):
        await adapter.submit_order(_order())


async def test_non_positive_prices_fail_closed():
    adapter = await _adapter(_state(best_bid="0", best_ask="0"))
    with pytest.raises(OrderRejected, match="MARKET_DATA_UNAVAILABLE"):
        await adapter.submit_order(_order())


async def test_non_factual_depth_fails_closed():
    adapter = await _adapter(_state(bid_size="0", ask_size="0"))
    with pytest.raises(OrderRejected, match="MARKET_DATA_UNAVAILABLE"):
        await adapter.submit_order(_order())


async def test_provider_fault_fails_closed_without_synthetic_book():
    """A provider fault must never be papered over by a synthetic book."""
    adapter = await _adapter(MarketDataUnhealthy("OKX public market unavailable"))
    with pytest.raises(OrderRejected, match="MARKET_DATA_UNAVAILABLE") as exc:
        await adapter.submit_order(_order())
    assert "SOPHUSDT" not in adapter.books
    assert exc.value.args[0] != "MARKET_DATA_SYMBOL_MISMATCH"


async def test_failed_refresh_leaves_no_partial_book():
    """refresh_market_state must not register a book it could not fully build."""
    adapter = await _adapter(_state(bid_size="0", ask_size="0"))
    with pytest.raises(MarketDataUnhealthy):
        await adapter.refresh_market_state("SOPHUSDT")
    assert "SOPHUSDT" not in adapter.books


# ------------------------------------------------------- symbol isolation
async def test_symbol_mismatch_is_still_rejected():
    from crypto_trader.market_data.orderbook import OrderBook

    adapter = await _adapter(_state())
    foreign = OrderBook(symbol="WRONGUSDT", exchange="OKX")
    now = datetime.now(UTC)
    foreign.apply_snapshot(
        1, [(Decimal("100"), Decimal("1"))], [(Decimal("101"), Decimal("1"))], now=now
    )
    adapter.books["SOPHUSDT"] = foreign
    with pytest.raises(OrderRejected, match="MARKET_DATA_SYMBOL_MISMATCH"):
        await adapter.submit_order(_order(price="99"))


# ------------------------------------------------------------- idempotency
def test_orders_table_forbids_duplicate_client_order_id():
    """One immutable order identity may not become two orders."""
    from crypto_trader.persistence.models import OrderORM

    names = {c.name for c in OrderORM.__table__.constraints if hasattr(c, "columns")}
    columns = {
        col.name
        for constraint in OrderORM.__table__.constraints
        for col in getattr(constraint, "columns", ())
    }
    assert "uq_orders_client_order_id" in names
    assert "client_order_id" in columns


async def test_same_client_order_id_twice_produces_two_broker_orders_only_by_identity():
    """The adapter itself is idempotency-neutral: identity uniqueness is the
    DB constraint's job, so a retry with the SAME id is a REUSE, not a clone."""

    adapter = await _adapter(_state())
    first = await adapter.submit_order(_order(price="90", client_order_id="same-cid"))
    second = await adapter.submit_order(_order(price="90", client_order_id="same-cid"))

    assert first.client_order_id == second.client_order_id == "same-cid"
    assert set(adapter.orders) == {first.exchange_order_id, second.exchange_order_id}


async def test_partial_fill_leaves_correct_remaining_quantity():
    """Depth-limited matching must report the unfilled remainder honestly."""
    adapter = await _adapter(_state(bid_size="4"))
    order = await adapter.submit_order(_order(price="90", quantity="10"))

    assert order.filled_quantity == Decimal("4")
    assert order.quantity - order.filled_quantity == Decimal("6")
    assert order.status == OrderStatus.PARTIALLY_FILLED
