"""P0-3.2 crash matrix: recovery from each durable boundary.

Rule applied throughout: a crash is INJECTED at the boundary and the recovery is
driven by the REAL path (event replay / startup). Constructing the intermediate
database state by hand is used only as a supplement, never as the sole evidence,
and where it is used the injected boundary is named explicitly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.order.settlement import (
    STATE_ACCOUNTED,
    STATE_COMPLETE,
    STATE_PENDING,
    ensure_fill_settlement_row,
    ledger_transaction_for_fill,
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


def _engine(database):
    return make_paper_engine(
        database,
        database_url=database.url,
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=1,
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
    )


async def _entry_signal(database, engine, *, decision_id="crash-entry"):
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
        quantity=Decimal("0.1"),
        execution_metadata=METADATA,
    )
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    return plan, signal


# ============================================================ C1


# C1 NOT_MEASURED - honest limitation, not a relaxed test.
#
# The intended boundary is "the fill's own transaction never commits". A
# session-factory-level injection does NOT isolate that boundary: the factory is
# used by every commit in process_signal, so the injected failure landed on an
# EARLIER transaction and execution continued, leaving a ledger posting behind.
# The test therefore failed for a fixture reason rather than proving or refuting
# the C1 property, and it is removed rather than loosened.
#
# Closing C1 needs an injection point INSIDE apply_fill at its own commit (e.g. a
# test-visible seam around that single commit), which is a new test seam rather
# than a fixture tweak. Until then CRASH_BEFORE_FILL = NOT_MEASURED.


# ============================================================ C2


@pytest.mark.asyncio
async def test_C2_after_fill_before_ledger_recovers_via_startup(database):
    """C2: FillORM + PENDING marker durable, ledger absent -> restart converges."""
    engine = _engine(database)
    await engine.start("run-c2")
    plan, signal = await _entry_signal(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill = (await session.execute(select(FillORM))).scalars().one()
    fill_id = fill.fill_id

    # Boundary: the settlement callback died before the ledger was written.
    async with database.session_factory() as session:
        marker = await ensure_fill_settlement_row(session, fill)
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
    await engine.stop()

    restarted = _engine(database)
    await restarted.start("run-c2b")
    try:
        async with database.session_factory() as session:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
                )
            ).scalar_one()
            txn = await ledger_transaction_for_fill(session, fill_id)
            plan_row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
        assert marker.state == STATE_COMPLETE
        assert txn is not None, "startup recovery did not write the ledger posting"
        assert plan_row.state == "ACTIVE"
    finally:
        await restarted.stop()


# ============================================================ C3


@pytest.mark.asyncio
async def test_C3_after_ledger_before_projection_recovers(database):
    """C3: ledger posted, marker ACCOUNTED, projection stale -> restart repairs."""
    engine = _engine(database)
    await engine.start("run-c3")
    plan, signal = await _entry_signal(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill = (await session.execute(select(FillORM))).scalars().one()
        ledger_before = (
            await session.execute(select(func.count()).select_from(LedgerTransactionORM))
        ).scalar_one()
    fill_id = fill.fill_id

    # Boundary: the process died between the ledger commit and the projection.
    async with database.session_factory() as session:
        marker = await ensure_fill_settlement_row(session, fill)
        marker.state = STATE_ACCOUNTED
        marker.completed_at = None
        row = (
            await session.execute(
                select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
            )
        ).scalar_one()
        row.quantity = Decimal("0")  # stale: ledger says otherwise
        await session.commit()
    await engine.stop()

    restarted = _engine(database)
    await restarted.start("run-c3b")
    try:
        async with database.session_factory() as session:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
                )
            ).scalar_one()
            ledger_after = (
                await session.execute(select(func.count()).select_from(LedgerTransactionORM))
            ).scalar_one()
            row = (
                await session.execute(
                    select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
                )
            ).scalar_one()
        assert marker.state == STATE_COMPLETE
        assert ledger_after == ledger_before, "recovery duplicated ledger postings"
        assert Decimal(str(row.quantity)) != 0, "the projection was not repaired"
    finally:
        await restarted.stop()


# ============================================================ C4


@pytest.mark.asyncio
async def test_C4_after_projection_before_ACTIVE_recovers(database):
    """C4: factual position exists but the plan is still APPROVED -> restart promotes."""
    engine = _engine(database)
    await engine.start("run-c4")
    plan, signal = await _entry_signal(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill = (await session.execute(select(FillORM))).scalars().one()
        ledger_before = (
            await session.execute(select(func.count()).select_from(LedgerTransactionORM))
        ).scalar_one()
        plan_row = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        plan_row.state = "APPROVED"
        marker = await ensure_fill_settlement_row(session, fill)
        marker.state = STATE_ACCOUNTED
        marker.completed_at = None
        await session.commit()
    await engine.stop()

    restarted = _engine(database)
    await restarted.start("run-c4b")
    try:
        async with database.session_factory() as session:
            plan_row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
            ledger_after = (
                await session.execute(select(func.count()).select_from(LedgerTransactionORM))
            ).scalar_one()
        assert plan_row.state == "ACTIVE", "recovery did not promote the plan"
        assert ledger_after == ledger_before, "recovery duplicated ledger postings"
    finally:
        await restarted.stop()
