"""§65/§66/§77/§78: evidence persistence must be truthful, idempotent and fail-soft.

The store sits on the trading path, so the two properties that matter most are
that a telemetry failure can never raise into the caller, and that no value is
ever invented when it could not be measured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.execution_observability.evidence import (
    NOT_MEASURED,
    QUALITY_UNKNOWN,
    EntryEvidenceStore,
    EntryIntentEvidence,
    ratio,
)
from crypto_trader.market_data.orderbook import MarketDataStatus, OrderBook
from crypto_trader.persistence.models import (
    EntryExecutionEvidenceORM,
    EntryOrderbookSampleORM,
    MarketSnapshotORM,
)


def _book(*, bids=None, asks=None, status=MarketDataStatus.HEALTHY) -> OrderBook:
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal(p), Decimal(q)) for p, q in (bids or [("100", "2")])],
        [(Decimal(p), Decimal(q)) for p, q in (asks or [("101", "3")])],
    )
    if status is not MarketDataStatus.HEALTHY:
        book.status = status
    return book


def test_ratio_is_none_when_the_denominator_is_undefined():
    """A missing target is not the same fact as zero realisation."""
    assert ratio("10", "100") == "0.1"
    assert ratio("10", "0") is None
    assert ratio("10", None) is None
    assert ratio(None, "100") is None


@pytest.mark.asyncio
async def test_entry_intent_records_all_three_exposures_and_the_ratio(database):
    store = EntryEvidenceStore(database.session_factory)
    eid = await store.record_entry_intent(
        EntryIntentEvidence(
            symbol="BTCUSDT",
            side="BUY",
            chief_direction="LONG",
            decision_id="dec-1",
            trade_plan_id="plan-1",
            target_quantity="20000",
            target_notional="600000",
            risk_approved_max_quantity="20000",
            risk_approved_max_notional="600000",
            requested_order_quantity="20000",
            requested_order_notional="600000",
            actual_opened_quantity="500",
            actual_opened_notional="15000",
            leverage="5",
            limit_price="101",
        ),
        book=_book(),
        consume_side="ASK",
    )
    assert eid is not None
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(EntryExecutionEvidenceORM).where(
                    EntryExecutionEvidenceORM.evidence_id == eid
                )
            )
        ).scalar_one()
    # The three exposures stay distinct - this is the whole point of §14.
    assert row.target_notional == "600000"
    assert row.requested_order_notional == "600000"
    assert row.actual_opened_notional == "15000"
    assert row.exposure_realization_ratio == "0.025"
    assert row.executable_side == "ASK"
    assert row.executable_depth_l1 == "3"
    assert row.quality == "OK"


@pytest.mark.asyncio
async def test_pre_submit_snapshot_is_persisted_and_linked(database):
    store = EntryEvidenceStore(database.session_factory)
    eid = await store.record_entry_intent(
        EntryIntentEvidence(symbol="BTCUSDT", target_notional="1000"),
        book=_book(),
        consume_side="ASK",
    )
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(EntryExecutionEvidenceORM).where(
                    EntryExecutionEvidenceORM.evidence_id == eid
                )
            )
        ).scalar_one()
        snap = (
            await s.execute(
                select(MarketSnapshotORM).where(MarketSnapshotORM.id == row.pre_submit_snapshot_id)
            )
        ).scalar_one()
    assert snap.symbol == "BTCUSDT"
    assert snap.metrics_json is not None
    # The raw levels the existing table already stored remain populated too.
    assert snap.bids_json and "100" in snap.bids_json
    assert snap.asks_json and "101" in snap.asks_json


@pytest.mark.asyncio
async def test_unreadable_book_is_unknown_not_fabricated(database):
    store = EntryEvidenceStore(database.session_factory)
    eid = await store.record_entry_intent(
        EntryIntentEvidence(symbol="BTCUSDT", target_notional="1000"),
        book=_book(status=MarketDataStatus.UNHEALTHY),
        consume_side="ASK",
    )
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(EntryExecutionEvidenceORM).where(
                    EntryExecutionEvidenceORM.evidence_id == eid
                )
            )
        ).scalar_one()
    assert row.executable_depth_l1 is None
    assert row.quality == QUALITY_UNKNOWN


@pytest.mark.asyncio
async def test_missing_book_records_unknown_rather_than_a_guess(database):
    store = EntryEvidenceStore(database.session_factory)
    eid = await store.record_entry_intent(
        EntryIntentEvidence(symbol="BTCUSDT", target_notional="1000"), book=None
    )
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(EntryExecutionEvidenceORM).where(
                    EntryExecutionEvidenceORM.evidence_id == eid
                )
            )
        ).scalar_one()
    assert row.pre_submit_metrics_json is None
    assert row.quality == QUALITY_UNKNOWN


@pytest.mark.asyncio
async def test_sample_at_the_same_offset_is_idempotent(database):
    """A retried write must update, never duplicate, the same offset."""
    store = EntryEvidenceStore(database.session_factory)
    for _ in range(2):
        await store.record_sample(
            evidence_id="eev-fixed",
            symbol="BTCUSDT",
            offset_seconds=5,
            book=_book(),
            consume_side="ASK",
        )
    async with database.session_factory() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(EntryOrderbookSampleORM).where(
                    EntryOrderbookSampleORM.evidence_id == "eev-fixed"
                )
            )
        ).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_different_offsets_are_distinct_samples(database):
    store = EntryEvidenceStore(database.session_factory)
    for offset in (0, 1, 2):
        await store.record_sample(
            evidence_id="eev-multi", symbol="BTCUSDT", offset_seconds=offset,
            book=_book(), consume_side="ASK",
        )
    async with database.session_factory() as s:
        rows = (
            await s.execute(
                select(EntryOrderbookSampleORM.offset_seconds).where(
                    EntryOrderbookSampleORM.evidence_id == "eev-multi"
                )
            )
        ).scalars().all()
    assert sorted(rows) == [0, 1, 2]


@pytest.mark.asyncio
async def test_queue_ahead_is_not_measured_unless_supplied(database):
    """Fabricating queue priority would be worse than recording nothing."""
    store = EntryEvidenceStore(database.session_factory)
    await store.record_sample(
        evidence_id="eev-q", symbol="BTCUSDT", offset_seconds=0,
        book=_book(), consume_side="ASK",
    )
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(EntryOrderbookSampleORM).where(
                    EntryOrderbookSampleORM.evidence_id == "eev-q"
                )
            )
        ).scalar_one()
    assert row.queue_ahead == NOT_MEASURED
    assert row.queue_ahead_quality == NOT_MEASURED


@pytest.mark.asyncio
async def test_persistence_failure_never_raises_into_the_caller(database):
    """§78: telemetry must not be able to break trading."""

    class Boom:
        def __call__(self):
            raise RuntimeError("db is gone")

    store = EntryEvidenceStore(Boom())
    eid = await store.record_entry_intent(
        EntryIntentEvidence(symbol="BTCUSDT", target_notional="1"), book=_book()
    )
    assert eid is None                     # degraded, not raised
    assert store.degraded_writes >= 1
    assert store.last_error is not None


@pytest.mark.asyncio
async def test_sample_source_and_timestamps_are_recorded(database):
    store = EntryEvidenceStore(database.session_factory)
    observed = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    src_ts = observed - timedelta(milliseconds=250)
    await store.record_sample(
        evidence_id="eev-ts", symbol="BTCUSDT", offset_seconds=1,
        book=_book(), consume_side="ASK",
        source="OKX_PUBLIC", source_timestamp=src_ts, now=observed,
    )
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(EntryOrderbookSampleORM).where(
                    EntryOrderbookSampleORM.evidence_id == "eev-ts"
                )
            )
        ).scalar_one()
    assert row.source == "OKX_PUBLIC"
    assert row.observed_at is not None
    assert row.source_timestamp is not None


@pytest.mark.asyncio
async def test_snapshot_sequences_do_not_collide_for_sequenceless_books(database):
    """(symbol, sequence) is unique, so a book WITHOUT a venue sequence must still
    be capturable repeatedly - each capture is distinct evidence."""
    store = EntryEvidenceStore(database.session_factory)
    for _ in range(3):
        book = _book()
        book.sequence = None          # genuinely sequenceless, exercising the fallback
        await store.record_entry_intent(
            EntryIntentEvidence(symbol="BTCUSDT", target_notional="1"), book=book
        )
    async with database.session_factory() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(MarketSnapshotORM).where(
                    MarketSnapshotORM.symbol == "BTCUSDT"
                )
            )
        ).scalar_one()
    assert n == 3
    assert store.degraded_writes == 0


@pytest.mark.asyncio
async def test_a_real_sequence_collision_is_surfaced_not_swallowed(database):
    """Two captures claiming the SAME venue sequence cannot both be stored, and
    losing evidence must be recorded rather than silently treated as a duplicate."""
    store = EntryEvidenceStore(database.session_factory)
    for _ in range(2):
        book = _book()
        book.sequence = 42            # identical venue sequence both times
        await store.record_entry_intent(
            EntryIntentEvidence(symbol="BTCUSDT", target_notional="1"), book=book
        )
    async with database.session_factory() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(MarketSnapshotORM).where(
                    MarketSnapshotORM.symbol == "BTCUSDT"
                )
            )
        ).scalar_one()
    assert n == 1
    assert store.degraded_writes == 1
    assert store.last_error is not None and "collision" in store.last_error
