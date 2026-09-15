"""Phase 7 market races: REST snapshot vs WS deltas (disagreement/duplicates).

The canonical rule: a websocket sequence that does not continue the REST
snapshot sequence is never applied silently — the book is invalidated and
resynced, and only a fresh REST snapshot restores HEALTHY.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crypto_trader.domain.errors import SequenceGap
from crypto_trader.market_data.service import MarketDataService


def _bids(price: str) -> list[tuple[Decimal, Decimal]]:
    return [(Decimal(price), Decimal("1"))]


def _asks(price: str) -> list[tuple[Decimal, Decimal]]:
    return [(Decimal(price), Decimal("1"))]


async def test_rest_snapshot_then_next_ws_delta_is_healthy() -> None:
    service = MarketDataService()
    await service.ingest_snapshot("BTCUSDT", 100, _bids("100"), _asks("101"))
    book = await service.ingest_delta("BTCUSDT", 101, _bids("100.5"), _asks("101.5"))
    assert book.sequence == 101
    assert service.is_healthy("BTCUSDT") is True
    assert book.best_bid().price == Decimal("100.5")


async def test_stale_ws_sequence_against_rest_snapshot_never_applies() -> None:
    from crypto_trader.domain.errors import MarketDataUnhealthy

    service = MarketDataService()  # no REST snapshot provider -> resync impossible
    await service.ingest_snapshot("BTCUSDT", 100, _bids("100"), _asks("101"))
    assert service.is_healthy("BTCUSDT") is True

    # WS claims an older sequence than the REST snapshot (REST/WS disagreement).
    with pytest.raises((SequenceGap, MarketDataUnhealthy)):
        await service.ingest_delta("BTCUSDT", 90, _bids("99"), _asks("100"))
    assert service.is_healthy("BTCUSDT") is False

    # A fresh authoritative REST snapshot recovers the book.
    recovered = await service.ingest_snapshot("BTCUSDT", 200, _bids("102"), _asks("103"))
    assert service.is_healthy("BTCUSDT") is True
    assert recovered.best_bid().price == Decimal("102")


async def test_duplicate_ws_delta_is_not_double_counted_and_recovers() -> None:
    from crypto_trader.domain.errors import MarketDataUnhealthy

    service = MarketDataService()
    await service.ingest_snapshot("BTCUSDT", 100, _bids("100"), _asks("101"))
    first = await service.ingest_delta("BTCUSDT", 101, _bids("100.2"), _asks("101.2"))
    assert first.best_bid().price == Decimal("100.2")

    # Duplicate delivery of sequence 101 must not silently apply again.
    with pytest.raises((SequenceGap, MarketDataUnhealthy)):
        await service.ingest_delta("BTCUSDT", 101, _bids("500"), _asks("501"))
    assert service.is_healthy("BTCUSDT") is False

    recovered = await service.ingest_snapshot("BTCUSDT", 300, _bids("100.2"), _asks("101.2"))
    assert service.is_healthy("BTCUSDT") is True
    assert recovered.best_bid().price == Decimal("100.2")
