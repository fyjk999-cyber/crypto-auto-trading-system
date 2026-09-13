"""Correctness closure for the durable fill settlement implementation.

Two defects in 82caf94, both confirmed by the tests here:

  1. ``assert_prefix_settlement_history`` had the direction INVERTED. It tracked
     the first SETTLED fill and rejected a later unsettled one - i.e. it rejected
     the LEGAL shape (settled prefix, unfinished suffix) and accepted the ILLEGAL
     one (unfinished fill followed by a settled fill). The illegal shape is the
     dangerous one: the newer fill was settled against a position state that
     includes a fill whose own accounting was never proven.

  2. ``pending_settlements`` took the first N fills and filtered in Python, so
     once the oldest N were COMPLETE it returned nothing and recovery stopped
     early while unfinished fills remained.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.order.settlement import (
    STATE_COMPLETE,
    STATE_PENDING,
    SettlementHistoryContradiction,
    assert_prefix_settlement_history,
    pending_settlements,
)
from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


async def _add_fill(session, *, fill_id, symbol, offset_minutes, settled, state=None):
    session.add(
        FillORM(
            fill_id=fill_id,
            order_id="ord_seed",
            symbol=symbol,
            side="BUY",
            price=Decimal("100"),
            quantity=Decimal("1"),
            fee=Decimal("0"),
            timestamp=BASE_TIME + timedelta(minutes=offset_minutes),
        )
    )
    if settled:
        session.add(
            LedgerTransactionORM(
                transaction_id=f"txn_{fill_id}",
                entry_type="TRADE",
                account_id="default",
                fill_id=fill_id,
                created_at=BASE_TIME,
                ownership_status="OWNED",
            )
        )
    if state is not None:
        session.add(
            FillSettlementORM(
                fill_id=fill_id,
                order_id="ord_seed",
                symbol=symbol,
                state=state,
                attempt_count=0,
                created_at=BASE_TIME,
                updated_at=BASE_TIME,
            )
        )


# ---------------------------------------------------------------- prefix (T1-T6)


@pytest.mark.asyncio
async def test_T1_settled_prefix_then_pending_suffix_is_legal(database):
    async with database.session_factory() as session:
        await _add_fill(session, fill_id="f1", symbol="BTCUSDT", offset_minutes=1, settled=True)
        await _add_fill(session, fill_id="f2", symbol="BTCUSDT", offset_minutes=2, settled=True)
        await _add_fill(session, fill_id="f3", symbol="BTCUSDT", offset_minutes=3, settled=False)
        await session.commit()
        await assert_prefix_settlement_history(session)  # must NOT raise


@pytest.mark.asyncio
async def test_T2_pending_then_settled_is_illegal(database):
    async with database.session_factory() as session:
        await _add_fill(session, fill_id="f1", symbol="BTCUSDT", offset_minutes=1, settled=False)
        await _add_fill(session, fill_id="f2", symbol="BTCUSDT", offset_minutes=2, settled=True)
        await session.commit()
        with pytest.raises(SettlementHistoryContradiction):
            await assert_prefix_settlement_history(session)


@pytest.mark.asyncio
async def test_T3_all_settled_is_legal(database):
    async with database.session_factory() as session:
        for i in range(4):
            await _add_fill(
                session, fill_id=f"f{i}", symbol="BTCUSDT", offset_minutes=i, settled=True
            )
        await session.commit()
        await assert_prefix_settlement_history(session)


@pytest.mark.asyncio
async def test_T4_all_pending_is_legal(database):
    async with database.session_factory() as session:
        for i in range(4):
            await _add_fill(
                session, fill_id=f"f{i}", symbol="BTCUSDT", offset_minutes=i, settled=False
            )
        await session.commit()
        await assert_prefix_settlement_history(session)


@pytest.mark.asyncio
async def test_T5_contradiction_is_per_symbol(database):
    """BTC legal, ETH illegal: only ETH must block, and it must block."""
    async with database.session_factory() as session:
        await _add_fill(session, fill_id="b1", symbol="BTCUSDT", offset_minutes=1, settled=True)
        await _add_fill(session, fill_id="b2", symbol="BTCUSDT", offset_minutes=2, settled=False)
        await _add_fill(session, fill_id="e1", symbol="ETHUSDT", offset_minutes=3, settled=False)
        await _add_fill(session, fill_id="e2", symbol="ETHUSDT", offset_minutes=4, settled=True)
        await session.commit()
        with pytest.raises(SettlementHistoryContradiction) as excinfo:
            await assert_prefix_settlement_history(session)
        assert "ETHUSDT" in str(excinfo.value)


@pytest.mark.asyncio
async def test_T6_equal_timestamps_use_fill_id_ordering(database):
    async with database.session_factory() as session:
        await _add_fill(
            session,
            fill_id="a_settled",
            symbol="BTCUSDT",
            offset_minutes=1,
            settled=True,
        )
        await _add_fill(
            session,
            fill_id="b_pending",
            symbol="BTCUSDT",
            offset_minutes=1,
            settled=False,
        )
        await session.commit()
        # Deterministic: sorted by fill_id, "a_settled" precedes "b_pending".
        await assert_prefix_settlement_history(session)

        await _add_fill(
            session,
            fill_id="a0_pending",
            symbol="ETHUSDT",
            offset_minutes=1,
            settled=False,
        )
        await _add_fill(
            session,
            fill_id="b0_settled",
            symbol="ETHUSDT",
            offset_minutes=1,
            settled=True,
        )
        await session.commit()
        with pytest.raises(SettlementHistoryContradiction):
            await assert_prefix_settlement_history(session)


# ------------------------------------------------------------ pagination (§6/§7)


@pytest.mark.asyncio
async def test_pending_pagination_does_not_stop_at_the_first_batch(database):
    """250 fills: 220 COMPLETE then 30 PENDING. A limit of 20 must return
    the OLDEST PENDING fills, not nothing."""
    async with database.session_factory() as session:
        for i in range(1, 251):
            settled = i <= 220
            await _add_fill(
                session,
                fill_id=f"fill{i:04d}",
                symbol="BTCUSDT",
                offset_minutes=i,
                settled=settled,
                state=STATE_COMPLETE if settled else STATE_PENDING,
            )
        await session.commit()

        first = await pending_settlements(session, limit=20)
        assert [f.fill_id for f in first] == [f"fill{i:04d}" for i in range(221, 241)]

        for f in first:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == f.fill_id)
                )
            ).scalar_one()
            marker.state = STATE_COMPLETE
        await session.commit()

        second = await pending_settlements(session, limit=20)
        assert [f.fill_id for f in second] == [f"fill{i:04d}" for i in range(241, 251)]

        for f in second:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == f.fill_id)
                )
            ).scalar_one()
            marker.state = STATE_COMPLETE
        await session.commit()

        assert await pending_settlements(session, limit=20) == []


@pytest.mark.asyncio
async def test_unmarked_fill_without_ledger_is_included(database):
    """A fill with no marker is not assumed settled."""
    async with database.session_factory() as session:
        await _add_fill(
            session,
            fill_id="no_marker",
            symbol="BTCUSDT",
            offset_minutes=1,
            settled=False,
        )
        await session.commit()
        rows = await pending_settlements(session, limit=10)
        assert [f.fill_id for f in rows] == ["no_marker"]


@pytest.mark.asyncio
async def test_migration_backfill_semantics(database):
    """§9: ledger present -> ACCOUNTED, ledger absent -> PENDING, both scanned."""
    async with database.session_factory() as session:
        await _add_fill(
            session,
            fill_id="with_ledger",
            symbol="BTCUSDT",
            offset_minutes=1,
            settled=True,
        )
        await _add_fill(
            session,
            fill_id="no_ledger",
            symbol="BTCUSDT",
            offset_minutes=2,
            settled=False,
        )
        await session.commit()
        # Apply the migration's backfill rule.
        for row in (await session.execute(select(FillORM))).scalars().all():
            txn = (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.fill_id == row.fill_id
                    )
                )
            ).scalar_one_or_none()
            session.add(
                FillSettlementORM(
                    fill_id=row.fill_id,
                    order_id=row.order_id,
                    symbol=row.symbol,
                    state="ACCOUNTED" if txn is not None else STATE_PENDING,
                    attempt_count=0,
                    created_at=BASE_TIME,
                    updated_at=BASE_TIME,
                )
            )
        await session.commit()

        states = {
            m.fill_id: m.state
            for m in (await session.execute(select(FillSettlementORM))).scalars().all()
        }
        assert states["with_ledger"] == "ACCOUNTED"
        assert states["no_ledger"] == STATE_PENDING

        # ACCOUNTED != COMPLETE: both must be picked up by recovery.
        scanned = {f.fill_id for f in await pending_settlements(session, limit=10)}
        assert scanned == {"with_ledger", "no_ledger"}
