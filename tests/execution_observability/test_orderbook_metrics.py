"""§12/§66: the pre-submit metric set must be exact, or explicitly UNKNOWN.

These are pure functions over an OrderBook, so every assertion here is
deterministic and cannot depend on a clock, a network or a database.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crypto_trader.execution_observability.orderbook_metrics import (
    UNKNOWN,
    compute_orderbook_metrics,
)
from crypto_trader.market_data.orderbook import MarketDataStatus, OrderBook


def _book(
    *,
    bids: list[tuple[str, str]] | None = None,
    asks: list[tuple[str, str]] | None = None,
    status: MarketDataStatus = MarketDataStatus.HEALTHY,
) -> OrderBook:
    """Build a book from one factual snapshot. apply_snapshot replaces BOTH
    sides, so bids and asks must be supplied together."""
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal(p), Decimal(q)) for p, q in (bids or [])],
        [(Decimal(p), Decimal(q)) for p, q in (asks or [])],
    )
    if status is not MarketDataStatus.HEALTHY:
        # apply_snapshot always marks the book HEALTHY; re-apply the requested
        # status afterwards so the STALE case is genuinely exercised.
        book.status = status
    return book


def test_full_book_metrics_are_exact():
    book = _book(
        bids=[("100", "2"), ("99", "3"), ("98", "5")],
        asks=[("101", "1"), ("102", "4"), ("103", "6")],
    )
    m = compute_orderbook_metrics(book)
    assert m.best_bid == "100"
    assert m.best_ask == "101"
    assert m.mid == "100.5"
    # spread / mid * 10000 = 1/100.5*10000
    assert m.spread_bps is not None and Decimal(m.spread_bps) > 0
    assert m.bid_depth_l1 == "2"
    assert m.ask_depth_l1 == "1"
    assert m.bid_depth_l5 == "10"      # 2+3+5
    assert m.ask_depth_l5 == "11"      # 1+4+6
    assert m.quality == "OK"
    assert m.levels_captured >= 3


def test_microprice_leans_toward_the_heavier_opposite_side():
    # A heavy BID queue should pull microprice ABOVE the mid.
    book = _book(bids=[("100", "100")], asks=[("102", "1")])
    m = compute_orderbook_metrics(book)
    assert m.microprice is not None
    assert Decimal(m.microprice) > Decimal("101")   # above mid


def test_imbalance_sign_follows_bid_minus_ask():
    book = _book(bids=[("100", "10")], asks=[("101", "5")])
    m = compute_orderbook_metrics(book)
    assert m.orderbook_imbalance is not None
    assert Decimal(m.orderbook_imbalance) > 0    # more bid depth


def test_executable_side_is_recorded_only_when_asked_and_uses_consumed_side():
    """A LONG entry consumes ASK depth; a SHORT consumes BID depth."""
    book = _book(bids=[("100", "7")], asks=[("101", "3")])
    long_m = compute_orderbook_metrics(book, consume_side="ASK")
    assert long_m.executable_side == "ASK"
    assert long_m.executable_depth_l1 == "3"      # asks, not bids
    short_m = compute_orderbook_metrics(book, consume_side="BID")
    assert short_m.executable_side == "BID"
    assert short_m.executable_depth_l1 == "7"     # bids, not asks


def test_no_consume_side_means_unknown_not_a_guess():
    book = _book(bids=[("100", "7")], asks=[("101", "3")])
    m = compute_orderbook_metrics(book)
    assert m.executable_side is None
    assert m.executable_depth_l1 is None


def test_invalid_consume_side_is_not_silently_accepted():
    book = _book(bids=[("100", "7")], asks=[("101", "3")])
    m = compute_orderbook_metrics(book, consume_side="SIDEWAYS")
    assert m.executable_side is None


def test_empty_book_is_unknown_not_zero_depth():
    """An unreadable book must never be recorded as a factual zero-depth market."""
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    m = compute_orderbook_metrics(book)
    assert m.best_bid is None and m.best_ask is None
    assert m.quality == UNKNOWN
    assert m.bid_depth_l1 is None


def test_non_healthy_book_yields_unknown_depth():
    """A non-HEALTHY book must fail closed: depth_quantity returns None rather
    than presenting a stale number as if it were fresh liquidity."""
    book = _book(bids=[("100", "5")], asks=[("101", "5")],
                 status=MarketDataStatus.UNHEALTHY)
    m = compute_orderbook_metrics(book)
    # depth_quantity fails closed on a non-HEALTHY book rather than reporting
    # a stale number as if it were fresh liquidity.
    assert m.bid_depth_l1 is None
    assert m.executable_depth_l1 is None


def test_negative_quantity_is_rejected_by_the_book():
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    with pytest.raises(ValueError):
        book.apply_snapshot(1, [(Decimal("100"), Decimal("-1"))], [])


def test_metrics_are_json_serialisable():
    import json

    book = _book(bids=[("100", "2")], asks=[("101", "3")])
    payload = compute_orderbook_metrics(book, consume_side="ASK").as_dict()
    json.dumps(payload)   # must not raise


def test_levels_are_best_first():
    book = _book(bids=[("98", "1"), ("100", "1"), ("99", "1")],
                 asks=[("103", "1"), ("101", "1"), ("102", "1")])
    m = compute_orderbook_metrics(book)
    assert [p for p, _ in m.bids] == ["100", "99", "98"]
    assert [p for p, _ in m.asks] == ["101", "102", "103"]
