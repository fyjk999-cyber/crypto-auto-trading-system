from decimal import Decimal

import pytest

from crypto_trader.domain.enums import MarketDataStatus
from crypto_trader.domain.errors import MarketDataUnhealthy, SequenceGap
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.market_data.websocket import WebSocketReconnectPolicy


def levels(*pairs):
    return [(Decimal(p), Decimal(q)) for p, q in pairs]


async def test_orderbook_snapshot_and_delta():
    book = OrderBook(symbol="BTCUSDT")
    book.apply_snapshot(10, levels(("100", "1"), ("99", "2")), levels(("101", "1.5"), ("102", "3")))
    assert book.sequence == 10
    assert book.best_bid().price == Decimal("100")
    assert book.best_ask().price == Decimal("101")
    book.apply_delta(11, levels(("100", "0")), levels(("101", "0.5")))
    assert book.best_bid().price == Decimal("99")
    assert book.best_ask().quantity == Decimal("0.5")


def test_orderbook_sequence_gap_invalidates_caller_side():
    book = OrderBook(symbol="BTCUSDT")
    book.apply_snapshot(10, levels(("100", "1")), levels(("101", "1")))
    with pytest.raises(SequenceGap):
        book.apply_delta(12, levels(("100", "1")), levels(("101", "1")))


async def test_market_data_service_resyncs_after_gap():
    seq = {"n": 10}

    async def provider(symbol):
        seq["n"] += 1
        return {"sequence": seq["n"], "bids": levels(("100", "1")), "asks": levels(("101", "1"))}

    svc = MarketDataService(snapshot_provider=provider)
    await svc.ingest_snapshot("BTCUSDT", 10, levels(("99", "1")), levels(("101", "1")))
    # valid delta
    await svc.ingest_delta("BTCUSDT", 11, levels(("99.5", "1")), levels(("101", "0")))
    # gap 13 -> resync snapshot 11? provider seq becomes 11; then delta 12 valid
    await svc.ingest_delta("BTCUSDT", 13, levels(("99.6", "1")), levels(("102", "1")))
    book = svc.books["BTCUSDT"]
    assert book.sequence == 11
    assert svc.is_healthy("BTCUSDT")


async def test_market_data_unhealthy_when_resync_fails():
    async def provider(symbol):
        raise ConnectionError("down")

    svc = MarketDataService(snapshot_provider=provider)
    await svc.ingest_snapshot("BTCUSDT", 10, levels(("99", "1")), levels(("101", "1")))
    with pytest.raises(MarketDataUnhealthy):
        await svc.ingest_delta("BTCUSDT", 12, levels(("99", "1")), levels(("101", "1")))
    assert svc.statuses["BTCUSDT"] == MarketDataStatus.UNHEALTHY
    assert not svc.is_healthy("BTCUSDT")


async def test_market_data_service_requires_snapshot_before_delta():
    svc = MarketDataService()
    with pytest.raises(MarketDataUnhealthy):
        await svc.ingest_delta("BTCUSDT", 1, levels(("99", "1")), levels(("101", "1")))


def test_websocket_reconnect_policy():
    policy = WebSocketReconnectPolicy(max_attempts=3)
    policy.on_connected()
    assert policy.attempts == 0
    policy.on_disconnected()
    assert policy.should_reconnect() is True
    assert policy.resync_required is True
    policy.on_disconnected()
    policy.on_disconnected()
    assert policy.should_reconnect() is True
    policy.on_disconnected()
    assert policy.exhausted() is True
    assert policy.should_reconnect() is False
