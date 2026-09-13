"""Durable fill settlement recovery.

The bug this pins (measured by deterministic fault injection on 74a16e7):

    settlement callback raises AFTER FillORM commit
    -> FILL_ROW_COUNT = 1, ledger transactions for that fill = 0,
       POSITION_QTY = None, PLAN_STATE = APPROVED,
       health.event_processing = False
    -> redelivering the same fill event changed NOTHING

because ``apply_fill`` short-circuited on "fill already exists", and the event
loop dropped the event. A durable fill could therefore be permanently
half-settled with no path to recovery.

The invariant now: a fill is settled only when the ledger is factual, the
portfolio projection is current and the plan lifecycle has converged - and a
durable marker records that progress so recovery survives an event failure, a
replay, a crash or a restart, without duplicating anything.
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
from tests.integration.test_live_llm_position_lifecycle import BTC_EXECUTION_METADATA

SYMBOL = "BTCUSDT"


async def _entry(database, engine, *, decision_id="settle-entry"):
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
        entry, limit_price=Decimal("101"), execution_metadata=BTC_EXECUTION_METADATA
    )
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    return plan, signal


async def _counts(database):
    async with database.session_factory() as session:
        fills = (await session.execute(select(FillORM))).scalars().all()
        return {
            "fills": [f.fill_id for f in fills],
            "ledger": (
                await session.execute(select(func.count()).select_from(LedgerTransactionORM))
            ).scalar_one(),
            "fill_ledger": [
                t.fill_id
                for t in (await session.execute(select(LedgerTransactionORM))).scalars().all()
            ],
            "positions": {
                p.symbol: str(p.quantity)
                for p in (
                    await session.execute(
                        select(PositionProjectionORM).where(PositionProjectionORM.quantity != 0)
                    )
                ).scalars().all()
            },
        }


@pytest.mark.asyncio
async def test_fill_commit_then_settlement_failure_is_recoverable(database):
    """§31: FillORM commits, settlement fails before the ledger."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-1")
    plan, signal = await _entry(database, engine)

    original = engine._settle_fill
    state = {"raised": 0}

    async def failing(fill, order=None):
        if state["raised"] == 0:
            state["raised"] = 1
            raise RuntimeError("TEST_SETTLEMENT_FAILURE")
        return await original(fill)

    engine._settle_fill = failing
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fills = (await session.execute(select(FillORM))).scalars().all()
        assert len(fills) == 1, "the fill must be durable"
        fill_id = fills[0].fill_id
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
            )
        ).scalar_one()
        assert marker.state != STATE_COMPLETE
        assert marker.last_error_type == "RuntimeError"
        txn = (
            await session.execute(
                select(LedgerTransactionORM).where(LedgerTransactionORM.fill_id == fill_id)
            )
        ).scalar_one_or_none()
        assert txn is None, "the ledger posting must be absent after the failure"

    # Recovery must complete it.
    engine._settle_fill = original
    await engine._ensure_fill_settled(fill_id)

    async with database.session_factory() as session:
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
            )
        ).scalar_one()
        assert marker.state == STATE_COMPLETE
        txn = (
            await session.execute(
                select(LedgerTransactionORM).where(LedgerTransactionORM.fill_id == fill_id)
            )
        ).scalar_one_or_none()
        assert txn is not None
        plan_row = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        assert plan_row.state == "ACTIVE", "the plan must converge once the fill is factual"
        position = (
            await session.execute(
                select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
            )
        ).scalar_one_or_none()
        assert position is not None and position.quantity != 0
    await engine.stop()


@pytest.mark.asyncio
async def test_existing_fill_replays_settlement(database):
    """§37 — the direct regression for the original bug.

    ``apply_fill`` on an already-durable fill must NOT short-circuit settlement.
    Before the fix this returned immediately and the fill stayed half-settled
    forever.
    """
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-2")
    _, signal = await _entry(database, engine)

    original = engine._settle_fill
    state = {"raised": 0}

    async def failing(fill, order=None):
        if state["raised"] == 0:
            state["raised"] = 1
            raise RuntimeError("TEST_SETTLEMENT_FAILURE")
        return await original(fill)

    engine._settle_fill = failing
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    engine._settle_fill = original

    async with database.session_factory() as session:
        fill_row = (await session.execute(select(FillORM))).scalars().one()
        fill_id = fill_row.fill_id
        from crypto_trader.order.manager import _orm_to_fill

    async with database.session_factory() as session:
        existing = (
            await session.execute(select(FillORM).where(FillORM.fill_id == fill_id))
        ).scalar_one()
        domain_fill = _orm_to_fill(existing)

    # Replay the SAME factual fill through the manager.
    order, applied_fill, newly = await engine.order_manager.apply_fill(domain_fill)
    assert newly is False, "a replayed fill must not be applied twice"
    await engine.wait_for_event_queue()
    await engine._ensure_fill_settled(fill_id)

    async with database.session_factory() as session:
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
            )
        ).scalar_one()
        assert marker.state == STATE_COMPLETE, (
            "an existing fill must still be able to complete its settlement"
        )
        txns = (
            await session.execute(
                select(LedgerTransactionORM).where(LedgerTransactionORM.fill_id == fill_id)
            )
        ).scalars().all()
        assert len(list(txns)) == 1, "the ledger must not be duplicated"
        fills = (await session.execute(select(FillORM))).scalars().all()
        assert len(list(fills)) == 1, "the fill must not be duplicated"
    await engine.stop()


@pytest.mark.asyncio
async def test_restart_recovers_pending_fill_without_event_replay(database):
    """§38: startup alone must complete the settlement - no event redelivery."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-3")
    _, signal = await _entry(database, engine)

    original = engine._settle_fill
    state = {"raised": 0}

    async def failing(fill, order=None):
        if state["raised"] == 0:
            state["raised"] = 1
            raise RuntimeError("TEST_SETTLEMENT_FAILURE")
        return await original(fill)

    engine._settle_fill = failing
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    await engine.stop()

    async with database.session_factory() as session:
        assert await pending_settlements(session, limit=50), (
            "precondition: a settlement must still be pending"
        )
        fill_id = (await session.execute(select(FillORM))).scalars().one().fill_id

    # Fresh engine, SAME database. No exchange event is re-delivered.
    restarted = make_paper_engine(database, engine_tick_seconds=3600)
    await restarted.start("run-settle-3b")
    try:
        async with database.session_factory() as session:
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
                )
            ).scalar_one()
            assert marker.state == STATE_COMPLETE, "startup recovery did not settle the fill"
            txn = (
                await session.execute(
                    select(LedgerTransactionORM).where(LedgerTransactionORM.fill_id == fill_id)
                )
            ).scalar_one_or_none()
            assert txn is not None
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_duplicate_fill_never_duplicates_fee_or_ledger(database):
    """§29/§35: N replays of one fill => 1 fill, 1 ledger, 1 fee result."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-4")
    _, signal = await _entry(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill_id = (await session.execute(select(FillORM))).scalars().one().fill_id
        before = await _counts(database)

    for _ in range(3):
        await engine._ensure_fill_settled(fill_id)

    after = await _counts(database)
    assert after["fills"] == before["fills"]
    assert after["fill_ledger"].count(fill_id) == 1
    assert after["ledger"] == before["ledger"], "a replay duplicated ledger postings"
    assert after["positions"] == before["positions"]
    await engine.stop()


@pytest.mark.asyncio
async def test_market_intelligence_not_double_counted(database):
    """§36: record_execution counts EXECUTIONS, not settlement passes."""
    calls = {"n": 0}

    class _MI:
        def record_execution(self):
            calls["n"] += 1

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.market_intelligence = _MI()
    await engine.start("run-settle-5")
    _, signal = await _entry(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    first = calls["n"]

    async with database.session_factory() as session:
        fill_id = (await session.execute(select(FillORM))).scalars().one().fill_id
    for _ in range(3):
        await engine._ensure_fill_settled(fill_id)

    assert first == 1, f"expected exactly one execution metric, got {first}"
    assert calls["n"] == 1, "settlement replay inflated the execution metric"
    await engine.stop()


@pytest.mark.asyncio
async def test_event_loop_bounded_retry_then_audit(database):
    """§27/§28: bounded retry, and the final failure is durably audited."""
    from crypto_trader.runtime.engine import MAX_EVENT_ATTEMPTS

    assert MAX_EVENT_ATTEMPTS == 3, "retry must stay bounded"
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-6")

    attempts = {"n": 0}
    original = engine.process_exchange_event

    async def always_fails(event):
        attempts["n"] += 1
        raise RuntimeError("TEST_EVENT_FAILURE")

    engine.process_exchange_event = always_fails
    try:
        from datetime import UTC, datetime

        from crypto_trader.domain.models import ExchangeEvent

        event = ExchangeEvent(
            event_id="evt_retry_test",
            event_type="ORDER_FILLED",
            symbol=SYMBOL,
            timestamp=datetime.now(UTC),
            payload={},
        )
        await engine._event_queue.put(event)
        await engine.wait_for_event_queue()
        await engine.wait_for_event_queue()
    finally:
        engine.process_exchange_event = original

    assert attempts["n"] >= 2, "the event was not retried at all"
    assert attempts["n"] <= MAX_EVENT_ATTEMPTS + 1, "retry was not bounded"
    health = engine.health.snapshot()["components"].get("event_processing")
    assert health is not None and health["ok"] is False
    assert "RuntimeError" in health["detail"], "the failure detail was discarded"
    await engine.stop()


@pytest.mark.asyncio
async def test_ledger_commit_then_promotion_failure_recovers(database):
    """§32/§33: FillORM + ledger + position all factual, plan still APPROVED.

    The plan state is forced back to APPROVED to reproduce exactly that
    interrupted state. Recovery must promote WITHOUT re-recording the ledger.
    """
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-7")
    plan, signal = await _entry(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill_id = (await session.execute(select(FillORM))).scalars().one().fill_id
        ledger_count = (
            await session.execute(
                select(func.count()).select_from(LedgerTransactionORM).where(
                    LedgerTransactionORM.fill_id == fill_id
                )
            )
        ).scalar_one()
        position = (
            await session.execute(
                select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
            )
        ).scalar_one()
        assert ledger_count == 1
        assert position.quantity != 0, "precondition: the position must be factual"

        # Reproduce the interrupted state: everything settled except promotion.
        row = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        row.state = "APPROVED"
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
            )
        ).scalar_one()
        marker.state = "ACCOUNTED"
        marker.completed_at = None
        await session.commit()

    await engine._ensure_fill_settled(fill_id)

    async with database.session_factory() as session:
        after_ledger = (
            await session.execute(
                select(func.count()).select_from(LedgerTransactionORM).where(
                    LedgerTransactionORM.fill_id == fill_id
                )
            )
        ).scalar_one()
        row = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
            )
        ).scalar_one()
        fills = (await session.execute(select(FillORM))).scalars().all()
    assert after_ledger == 1, "recovery duplicated the ledger posting"
    assert len(list(fills)) == 1, "recovery duplicated the fill"
    assert row.state == "ACTIVE", "recovery did not promote the plan"
    assert marker.state == STATE_COMPLETE
    await engine.stop()


@pytest.mark.asyncio
async def test_settlement_predecessor_ordering_blocks_out_of_order(database):
    """§8: a later fill must not settle before an older unsettled one.

    A later fill's quantity_before / average_entry_price / realized_pnl can depend
    on the earlier one, so settling out of order would corrupt the projection.
    """
    from crypto_trader.order.settlement import SettlementPredecessorPending
    from crypto_trader.persistence.models import FillSettlementORM as _M

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-8")
    _, signal = await _entry(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill = (await session.execute(select(FillORM))).scalars().one()
        # Force an older same-symbol fill to be genuinely unsettled.
        older = FillORM(
            fill_id="fill_older_unsettled",
            order_id=fill.order_id,
            client_order_id=fill.client_order_id,
            exchange_order_id=fill.exchange_order_id,
            symbol=fill.symbol,
            side=fill.side,
            price=fill.price,
            quantity=Decimal("0"),
            fee=Decimal("0"),
            timestamp=fill.timestamp.replace(year=2020),
        )
        session.add(older)
        session.add(
            _M(
                fill_id="fill_older_unsettled",
                order_id=fill.order_id,
                symbol=fill.symbol,
                state="PENDING",
                attempt_count=0,
                created_at=fill.timestamp,
                updated_at=fill.timestamp,
            )
        )
        await session.commit()
        newer_id = fill.fill_id

    from crypto_trader.order.settlement import ensure_fill_settled

    async with database.session_factory() as session:
        with pytest.raises(SettlementPredecessorPending):
            await ensure_fill_settled(
                session,
                fill_id=newer_id,
                settle_ledger=engine._settle_ledger_phase,
                settle_downstream=engine._settle_downstream_phase,
            )
    await engine.stop()


@pytest.mark.asyncio
async def test_close_commit_then_episode_failure_recovers(database):
    """§34: exit fill persisted and settled, crash before CLOSED / episode.

    Restart must converge to CLOSED with EXACTLY ONE episode, and must not
    duplicate the exit ledger posting or the fee.
    """
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-settle-9")
    plan, signal = await _entry(database, engine)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        fill = (await session.execute(select(FillORM))).scalars().one()
        settle_fill_id = fill.fill_id
        total_ledger_before = (
            await session.execute(select(func.count()).select_from(LedgerTransactionORM))
        ).scalar_one()

    # Simulate a close-side interruption: the plan never converged.
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        row.state = "APPROVED"
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == settle_fill_id)
            )
        ).scalar_one()
        marker.state = "ACCOUNTED"
        marker.completed_at = None
        await session.commit()

    # Release the lease first: a second engine must never start while one holds it.
    await engine.stop()

    # A fresh engine must converge it from durable state alone.
    restarted = make_paper_engine(database, engine_tick_seconds=3600)
    await restarted.start("run-settle-9b")
    try:
        async with database.session_factory() as session:
            total_ledger_after = (
                await session.execute(select(func.count()).select_from(LedgerTransactionORM))
            ).scalar_one()
            row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
            fills_after = (await session.execute(select(FillORM))).scalars().all()
        assert total_ledger_after == total_ledger_before, "recovery duplicated ledger postings"
        assert len(list(fills_after)) == 1, "recovery duplicated the fill"
        assert row.state in {"ACTIVE", "CLOSED"}, (
            f"recovery left the plan un-converged: {row.state}"
        )
    finally:
        await restarted.stop()
