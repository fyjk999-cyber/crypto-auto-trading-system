"""P0-3: a durable fill must be recoverable to COMPLETE.

The defect this closes (measured on the previous candidate by fault injection):

    settlement failed AFTER the FillORM commit
    -> FillORM = 1, ledger transactions for that fill = 0, position absent
    -> redelivering the SAME fill changed NOTHING

because ``apply_fill`` short-circuited on "fill already exists". A durable fill
could therefore stay permanently half-settled, and neither a replay nor a restart
could finish it.

Invariant: FillORM persisted != fill fully settled. A per-fill marker records
PENDING / ACCOUNTED / COMPLETE so any interruption is completable and no phase is
ever applied twice.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.order.settlement import (
    STATE_COMPLETE,
    STATE_PENDING,
    ensure_fill_settlement_row,
    ledger_transaction_for_fill,
    pending_settlements,
)
from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
    PositionProjectionORM,
    TradePlanORM,
)
from crypto_trader.trade_plan.service import TradePlanService
from tests.conftest import make_paper_engine

SYMBOL = "BTCUSDT"
METADATA = {
    "instrument_type": "LINEAR_PERP",
    "contract_size": 1,
    "contract_multiplier": 1,
    "leverage": 2,
    "direction": "LONG",
}


async def _await_fill(database, *, deadline_seconds: float = 5.0):
    import asyncio
    import time

    deadline = time.monotonic() + deadline_seconds
    while True:
        async with database.session_factory() as session:
            rows = (await session.execute(select(FillORM))).scalars().all()
        if rows:
            return rows
        if time.monotonic() >= deadline:
            raise AssertionError("no durable fill appeared")
        await asyncio.sleep(0.01)


async def _open_entry(database, engine, *, decision_id="settle-entry"):
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id=decision_id,
        symbol=SYMBOL,
        action="LONG",
        market_regime="TREND",
        thesis="t",
        position_size_request=0.1,
        leverage_request=10,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry,
        limit_price=Decimal("101"),
        # Sizing V2: the authoritative quantity must be supplied explicitly; the
        # advisory position_size_request is never an order quantity.
        quantity=Decimal("0.1"),
        execution_metadata=METADATA,
    )
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    return plan


def _engine(database):
    return make_paper_engine(
        database,
        database_url=database.url,
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=1,
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
    )


# --------------------------------------------------------- §4 atomic marker


@pytest.mark.asyncio
async def test_new_fill_gets_a_pending_marker_in_the_same_transaction(database):
    """Fill exists => settlement marker exists. No marker gap is allowed."""
    engine = _engine(database)
    await engine.start("run-p03-1")
    try:
        await _open_entry(database, engine)
        fills = await _await_fill(database)
        assert len(fills) == 1
        async with database.session_factory() as session:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(
                        FillSettlementORM.fill_id == fills[0].fill_id
                    )
                )
            ).scalar_one_or_none()
        assert marker is not None, "a durable fill was written with no settlement marker"
        assert marker.state in {STATE_PENDING, "ACCOUNTED", STATE_COMPLETE}
    finally:
        await engine.stop()


# ------------------------------------------------- §19/§31 crash: after fill


@pytest.mark.asyncio
async def test_ledger_failure_after_fill_commit_is_recoverable(database):
    """Crash between the fill commit and the ledger posting."""
    engine = _engine(database)
    await engine.start("run-p03-2")
    try:
        plan = await _open_entry(database, engine)
        fills = await _await_fill(database)
        fill_id = fills[0].fill_id

        # Reproduce the interrupted state: the fill is durable, its marker is not
        # complete, and no ledger posting exists for it.
        async with database.session_factory() as session:
            marker = await ensure_fill_settlement_row(session, fills[0])
            marker.state = STATE_PENDING
            marker.completed_at = None
            await session.delete(
                (
                    await session.execute(
                        select(LedgerTransactionORM).where(
                            LedgerTransactionORM.fill_id == fill_id
                        )
                    )
                ).scalar_one()
            )
            await session.commit()
        async with database.session_factory() as session:
            assert await ledger_transaction_for_fill(session, fill_id) is None

        await engine._ensure_fill_settled(fill_id)

        async with database.session_factory() as session:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
                )
            ).scalar_one()
            assert marker.state == STATE_COMPLETE
            txn = await ledger_transaction_for_fill(session, fill_id)
            assert txn is not None, "recovery did not write the ledger posting"
            position = (
                await session.execute(
                    select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
                )
            ).scalar_one_or_none()
            assert position is not None and position.quantity != 0
            plan_row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
            assert plan_row.state == "ACTIVE"
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_replay_of_a_settled_fill_duplicates_nothing(database):
    """§24: replaying the same fill must not duplicate any economic effect."""
    engine = _engine(database)
    await engine.start("run-p03-3")
    try:
        await _open_entry(database, engine)
        fills = await _await_fill(database)
        fill_id = fills[0].fill_id
        await engine._ensure_fill_settled(fill_id)

        async def snapshot():
            async with database.session_factory() as session:
                return {
                    "fills": (
                        await session.execute(select(func.count()).select_from(FillORM))
                    ).scalar_one(),
                    "ledger": (
                        await session.execute(
                            select(func.count()).select_from(LedgerTransactionORM)
                        )
                    ).scalar_one(),
                    "fill_ledger": (
                        await session.execute(
                            select(func.count())
                            .select_from(LedgerTransactionORM)
                            .where(LedgerTransactionORM.fill_id == fill_id)
                        )
                    ).scalar_one(),
                    "positions": (
                        await 
                            session.execute(select(func.count()).select_from(PositionProjectionORM))
                    ).scalar_one(),
                }

        before = await snapshot()
        for _ in range(3):
            await engine._ensure_fill_settled(fill_id)
        after = await snapshot()

        assert after["fills"] == before["fills"], "the fill was duplicated"
        assert after["ledger"] == before["ledger"], "a ledger posting was duplicated"
        assert after["fill_ledger"] == 1, "a fill must have exactly one ledger posting"
        assert after["positions"] == before["positions"], "the position was duplicated"
    finally:
        await engine.stop()


# ------------------------------------------------- §15 startup recovery


@pytest.mark.asyncio
async def test_startup_recovers_a_pending_settlement_without_event_replay(database):
    """§15: startup alone must complete an interrupted settlement."""
    engine = _engine(database)
    await engine.start("run-p03-4")
    plan = await _open_entry(database, engine)
    fills = await _await_fill(database)
    fill_id = fills[0].fill_id

    # Leave the state interrupted, then stop.
    async with database.session_factory() as session:
        marker = await ensure_fill_settlement_row(session, fills[0])
        marker.state = STATE_PENDING
        marker.completed_at = None
        await session.commit()
    await engine.stop()

    async with database.session_factory() as session:
        pending = await pending_settlements(session, limit=50)
        assert any(f.fill_id == fill_id for f in pending), "precondition: still pending"

    # A fresh engine over the SAME database, with no event redelivered.
    restarted = _engine(database)
    await restarted.start("run-p03-4b")
    try:
        async with database.session_factory() as session:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
                )
            ).scalar_one()
            assert marker.state == STATE_COMPLETE, "startup recovery did not settle the fill"
            assert await ledger_transaction_for_fill(session, fill_id) is not None
            plan_row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
            assert plan_row.state == "ACTIVE"
    finally:
        await restarted.stop()
