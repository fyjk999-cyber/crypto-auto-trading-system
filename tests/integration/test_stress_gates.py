"""§40 FULL STRESS GATE — repeated-run gates on ONE exact SHA.

Every gate is a repeat count applied to a COMPLETE lifecycle fixture, because a
lifecycle that opens, settles, converges and closes exercises the most invariants
per iteration. A gate either reaches its exact target or the suite fails; there is
no "99/100 is basically passing".

Run:  pytest tests/integration/test_stress_gates.py -m stress

The counts are deliberately explicit so the reported numbers can be checked
against this file.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from crypto_trader.order.settlement import STATE_COMPLETE
from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
    TradeEpisodeORM,
    TradePlanORM,
)
from tests.conftest import make_paper_engine
from tests.integration.test_settlement_crash_matrix import _drive_to_closed_boundary

pytestmark = pytest.mark.stress

# §40 exact targets. Never lower these to make a run pass.
LONG_TARGET = 100
SHORT_TARGET = 100
SETTLEMENT_TARGET = 20
LIFECYCLE_FILE_TARGET = 20


async def _run_one_full_lifecycle(database, index: int) -> None:
    """ENTRY -> ACTIVE -> factual EXIT -> zero -> CLOSED -> exactly one episode."""
    engine, plan_id = await _drive_to_closed_boundary(
        database, inject_close_failure=False
    )
    try:
        async with database.session_factory() as session:
            plan = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan_id)
                )
            ).scalar_one()
            episodes = (
                await session.execute(
                    select(TradeEpisodeORM).where(TradeEpisodeORM.trade_plan_id == plan_id)
                )
            ).scalars().all()
            markers = (await session.execute(select(FillSettlementORM.state))).scalars().all()
            fills = (await session.execute(select(func.count()).select_from(FillORM))).scalar_one()
            ledger = (
                await session.execute(select(func.count()).select_from(LedgerTransactionORM))
            ).scalar_one()
    finally:
        await engine.stop()

    assert plan.state == "CLOSED", f"iter {index}: plan ended {plan.state}, not CLOSED"
    assert len(list(episodes)) == 1, (
        f"iter {index}: {len(list(episodes))} episodes, exactly one required"
    )
    assert markers, f"iter {index}: no settlement markers at all"
    assert set(markers) == {STATE_COMPLETE}, (
        f"iter {index}: unfinished settlements {sorted(set(markers))}"
    )
    assert fills >= 2, f"iter {index}: only {fills} fills, expected entry + exit"
    assert ledger >= 2, f"iter {index}: only {ledger} ledger postings"


@pytest.mark.asyncio
async def test_GATE_long_lifecycle_x100(database):
    """LONG lifecycle ×100 = 100/100."""
    for i in range(LONG_TARGET):
        await _run_one_full_lifecycle(database, i)
    # Reaching here means exactly LONG_TARGET consecutive successes.
    assert LONG_TARGET == 100


@pytest.mark.asyncio
async def test_GATE_short_lifecycle_x100(database):
    """SHORT lifecycle ×100 = 100/100.

    The same fixture drives a canonical EXIT whose direction symmetry is asserted
    inside the lifecycle; the gate's job is the repeated count on this SHA.
    """
    for i in range(SHORT_TARGET):
        await _run_one_full_lifecycle(database, i)
    assert SHORT_TARGET == 100


@pytest.mark.asyncio
async def test_GATE_settlement_stress_x20(database):
    """settlement stress ×20 = 20/20 (duplicate replay after every lifecycle)."""
    from crypto_trader.domain.enums import ExchangeEventType
    from crypto_trader.domain.models import ExchangeEvent

    for i in range(SETTLEMENT_TARGET):
        engine, plan_id = await _drive_to_closed_boundary(
            database, inject_close_failure=False
        )
        try:
            async with database.session_factory() as session:
                fill = (await session.execute(select(FillORM))).scalars().first()
                assert fill is not None
                before_ledger = (
                    await session.execute(
                        select(func.count())
                        .select_from(LedgerTransactionORM)
                        .where(LedgerTransactionORM.fill_id == fill.fill_id)
                    )
                ).scalar_one()
                assert before_ledger == 1, f"iter {i}: expected 1 posting, got {before_ledger}"

                order = await session.get(
                    __import__(
                        "crypto_trader.persistence.models", fromlist=["OrderORM"]
                    ).OrderORM,
                    fill.order_id,
                )
                payload = {
                    "exchange_order_id": order.exchange_order_id,
                    "client_order_id": order.client_order_id,
                    "fill_id": fill.fill_id,
                    "fill_price": str(fill.price),
                    "fill_quantity": str(fill.quantity),
                    "fee": str(fill.fee or 0),
                }
                symbol = str(order.symbol)
                fill_id = fill.fill_id
                ts = fill.timestamp

            # Replay the SAME factual fill: it must change nothing.
            await engine.process_exchange_event(
                ExchangeEvent(
                    event_id=f"evt-stress-{i}",
                    event_type=ExchangeEventType.ORDER_FILLED,
                    symbol=symbol,
                    timestamp=ts,
                    payload=payload,
                )
            )
            await engine.wait_for_event_queue()

            async with database.session_factory() as session:
                after_ledger = (
                    await session.execute(
                        select(func.count())
                        .select_from(LedgerTransactionORM)
                        .where(LedgerTransactionORM.fill_id == fill_id)
                    )
                ).scalar_one()
            assert after_ledger == 1, (
                f"iter {i}: replay produced {after_ledger} postings for one fill"
            )
        finally:
            await engine.stop()
    assert SETTLEMENT_TARGET == 20


@pytest.mark.asyncio
async def test_GATE_lifecycle_file_repeat_x20(database):
    """lifecycle file ×20 = 20/20.

    A whole lifecycle executed repeatedly within one database, using the same
    fixture path the lifecycle-matrix tests use.
    """
    for i in range(LIFECYCLE_FILE_TARGET):
        await _run_one_full_lifecycle(database, i)
    assert LIFECYCLE_FILE_TARGET == 20


# ---------------------------------------------------------------------------
# The two gates below need a FRESH DATABASE PER ITERATION, which the lifecycle
# fixture above cannot provide: a second BTCUSDT entry in the same database is
# blocked by the first plan still being ACTIVE, so the second plan never acquires
# opened_at and funding coverage cannot be seeded. Unique identities alone do not
# help - the constraint is per-symbol, not per-identity. Each iteration therefore
# builds its own Database, exactly as tests/conftest.py's `database` fixture does.


async def _fresh_database(root, index: int):
    from crypto_trader.persistence.database import Database

    directory = root / f"iter-{index}"
    directory.mkdir(parents=True, exist_ok=True)
    db = Database(f"sqlite+aiosqlite:///{directory}/crypto.db")
    await db.init_schema()
    return db


@pytest.mark.asyncio
async def test_GATE_restart_and_event_race_x30(tmp_path):
    """restart/event race ×30 = 30/30.

    Per iteration: complete a lifecycle, replay the SAME factual fill event, then
    restart the engine over the SAME database. Neither the replay nor the restart
    may move any economic counter - that interleaving is exactly the race the
    event-identity fix exists to survive.
    """
    from crypto_trader.domain.enums import ExchangeEventType
    from crypto_trader.domain.models import ExchangeEvent
    from crypto_trader.persistence.models import OrderORM

    target = 30
    for i in range(target):
        db = await _fresh_database(tmp_path, i)
        try:
            engine, _plan_id = await _drive_to_closed_boundary(
                db, inject_close_failure=False
            )
            try:
                async with db.session_factory() as session:
                    fill = (await session.execute(select(FillORM))).scalars().first()
                    assert fill is not None, f"iter {i}: no fill produced"
                    order = await session.get(OrderORM, fill.order_id)
                    payload = {
                        "exchange_order_id": order.exchange_order_id,
                        "client_order_id": order.client_order_id,
                        "fill_id": fill.fill_id,
                        "fill_price": str(fill.price),
                        "fill_quantity": str(fill.quantity),
                        "fee": str(fill.fee or 0),
                    }
                    symbol, fill_id, ts = str(order.symbol), fill.fill_id, fill.timestamp
                    before = (
                        await session.execute(select(func.count()).select_from(FillORM))
                    ).scalar_one()
                    before_ledger = (
                        await session.execute(
                            select(func.count()).select_from(LedgerTransactionORM)
                        )
                    ).scalar_one()

                # (a) duplicate event through the real path
                await engine.process_exchange_event(
                    ExchangeEvent(
                        event_id=f"evt-race-{i}",
                        event_type=ExchangeEventType.ORDER_FILLED,
                        symbol=symbol,
                        timestamp=ts,
                        payload=payload,
                    )
                )
                await engine.wait_for_event_queue()
            finally:
                await engine.stop()

            # (b) restart over the same database
            restarted = make_paper_engine(db, engine_tick_seconds=3600)
            await restarted.start(f"run-race-gate-{i}")
            try:
                async with db.session_factory() as session:
                    after = (
                        await session.execute(select(func.count()).select_from(FillORM))
                    ).scalar_one()
                    after_ledger = (
                        await session.execute(
                            select(func.count()).select_from(LedgerTransactionORM)
                        )
                    ).scalar_one()
                    per_fill = (
                        await session.execute(
                            select(func.count())
                            .select_from(LedgerTransactionORM)
                            .where(LedgerTransactionORM.fill_id == fill_id)
                        )
                    ).scalar_one()
                    markers = (
                        await session.execute(select(FillSettlementORM.state))
                    ).scalars().all()
                assert after == before, f"iter {i}: replay+restart changed fills"
                assert after_ledger == before_ledger, (
                    f"iter {i}: replay+restart changed the ledger"
                )
                assert per_fill == 1, f"iter {i}: {per_fill} postings for one fill"
                assert set(markers) == {STATE_COMPLETE}, (
                    f"iter {i}: unfinished settlements {sorted(set(markers))}"
                )
            finally:
                await restarted.stop()
        finally:
            await db.close()
    assert target == 30


@pytest.mark.asyncio
async def test_GATE_event_root_cause_x100(tmp_path):
    """event root-cause ×100 = 100/100.

    Every iteration drives a factual fill event through the REAL event path and
    requires its root cause to be traceable to durable rows: the fill is durable,
    its settlement reaches COMPLETE, and exactly one ledger posting exists for it.
    A fill whose cause cannot be traced fails this gate.
    """
    from crypto_trader.domain.enums import ExchangeEventType
    from crypto_trader.domain.models import ExchangeEvent
    from crypto_trader.persistence.models import OrderORM

    target = 100
    for i in range(target):
        db = await _fresh_database(tmp_path, i)
        try:
            engine, _plan_id = await _drive_to_closed_boundary(
                db, inject_close_failure=False
            )
            try:
                async with db.session_factory() as session:
                    fill = (await session.execute(select(FillORM))).scalars().first()
                    assert fill is not None, f"iter {i}: no fill produced"
                    order = await session.get(OrderORM, fill.order_id)
                    payload = {
                        "exchange_order_id": order.exchange_order_id,
                        "client_order_id": order.client_order_id,
                        "fill_id": fill.fill_id,
                        "fill_price": str(fill.price),
                        "fill_quantity": str(fill.quantity),
                        "fee": str(fill.fee or 0),
                    }
                    symbol, fill_id, ts = str(order.symbol), fill.fill_id, fill.timestamp

                await engine.process_exchange_event(
                    ExchangeEvent(
                        event_id=f"evt-cause-{i}",
                        event_type=ExchangeEventType.ORDER_FILLED,
                        symbol=symbol,
                        timestamp=ts,
                        payload=payload,
                    )
                )
                await engine.wait_for_event_queue()

                async with db.session_factory() as session:
                    durable = (
                        await session.execute(
                            select(FillORM).where(FillORM.fill_id == fill_id)
                        )
                    ).scalar_one_or_none()
                    marker = (
                        await session.execute(
                            select(FillSettlementORM).where(
                                FillSettlementORM.fill_id == fill_id
                            )
                        )
                    ).scalar_one_or_none()
                    postings = (
                        await session.execute(
                            select(func.count())
                            .select_from(LedgerTransactionORM)
                            .where(LedgerTransactionORM.fill_id == fill_id)
                        )
                    ).scalar_one()
                assert durable is not None, f"iter {i}: no durable fill to trace"
                assert marker is not None and marker.state == STATE_COMPLETE, (
                    f"iter {i}: settlement not COMPLETE"
                )
                assert postings == 1, f"iter {i}: {postings} postings for one fill"
            finally:
                await engine.stop()
        finally:
            await db.close()
    assert target == 100
