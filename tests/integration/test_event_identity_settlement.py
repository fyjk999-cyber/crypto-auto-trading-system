"""§26: event identity and durable settlement must work as ONE mechanism.

The branch's event-identity fix lets a venue event resolve on the durable
``client_order_id`` when ``exchange_order_id`` has not been persisted yet - the
window in which the simulator emits ack/open/fill inline while submit is still in
flight. P0-3 then has to settle whatever fill that resolution produces.

Each was tested alone. Untested together, the failure mode is a resolved event
whose fill never reaches the ledger, or a settlement that re-applies when the
event arrives twice.

Boundary note (stated, not glossed): the pre-persistence state is CONSTRUCTED by
clearing the order's venue id, because the engine otherwise persists it during
submit. What is then exercised is the REAL public path - process_exchange_event
resolving on client id, apply_fill, the settlement driver, the ledger, the
projection and plan convergence.

The fixture leaves the order PARTIALLY filled (0.4 of 1) on purpose: the
constructed event then fills the remaining 0.6, which the order's own
over-quantity backstop accepts. Sizing the event larger would make the assertions
pass or fail for the wrong reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.domain.enums import ExchangeEventType
from crypto_trader.domain.models import ExchangeEvent
from crypto_trader.order.settlement import STATE_COMPLETE, ledger_transaction_for_fill
from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
    OrderORM,
    PositionProjectionORM,
    TradePlanORM,
)
from tests.conftest import make_paper_engine
from tests.integration.test_position_lifecycle_determinism import _open_long_position

FILL_ID = "fill-clientid-1"
DUP_FILL_ID = "fill-clientid-dup"
REMAINING = "0.6"


async def _clear_venue_id(database, internal_order_id: str) -> tuple[str, str]:
    """Simulate 'the fill arrived before exchange_order_id was persisted'.

    Returns (client_order_id, venue_id): the venue still knows the id and puts it
    in the event, but the engine has not written it to the order row yet.
    """
    async with database.session_factory() as session:
        row = await session.get(OrderORM, internal_order_id)
        assert row.exchange_order_id, "precondition: the order had a venue id"
        client_order_id = row.client_order_id
        venue_id = str(row.exchange_order_id)
        row.exchange_order_id = None
        await session.commit()
    return client_order_id, venue_id


def _fill_event(
    *, event_id: str, client_order_id: str, symbol: str, fill_id: str, venue_id: str
):
    """A venue event carrying the venue id the engine has NOT persisted yet."""
    return ExchangeEvent(
        event_id=event_id,
        event_type=ExchangeEventType.ORDER_FILLED,
        symbol=symbol,
        timestamp=datetime.now(UTC),
        payload={
            "exchange_order_id": venue_id,
            "client_order_id": client_order_id,
            "fill_id": fill_id,
            "fill_price": "100.05",
            "fill_quantity": REMAINING,
            "fee": "0.01",
        },
    )


async def _counts(database) -> dict:
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
            "ledger_for_fill": (
                await session.execute(
                    select(func.count())
                    .select_from(LedgerTransactionORM)
                    .where(LedgerTransactionORM.fill_id == DUP_FILL_ID)
                )
            ).scalar_one(),
            "positions": (
                await session.execute(
                    select(func.count()).select_from(PositionProjectionORM)
                )
            ).scalar_one(),
        }


@pytest.mark.asyncio
async def test_client_id_resolution_settles_end_to_end(database):
    """Resolve by client id -> durable fill -> settlement -> ledger -> projection."""
    engine, adapter, _, _, _, _ = await _open_long_position(
        database, quantity="1", ask_quantity="0.4"
    )
    try:
        entry = next(iter(adapter.orders.values()))
        local = await engine.order_manager.get_by_client(entry.client_order_id)
        assert local is not None
        client_order_id, venue_id = await _clear_venue_id(
            database, local.internal_order_id
        )

        await engine._enqueue_event(
            _fill_event(
                event_id="evt-clientid-1",
                client_order_id=client_order_id,
                symbol=local.symbol,
                fill_id=FILL_ID,
                venue_id=venue_id,
            )
        )
        await engine.wait_for_event_queue()

        async with database.session_factory() as session:
            fill = (
                await session.execute(select(FillORM).where(FillORM.fill_id == FILL_ID))
            ).scalar_one_or_none()
            assert fill is not None, (
                "the client-id resolution produced no durable fill - a factual fill "
                "was lost because exchange_order_id was not persisted yet"
            )
            marker = (
                await session.execute(
                    select(FillSettlementORM).where(FillSettlementORM.fill_id == FILL_ID)
                )
            ).scalar_one_or_none()
            assert marker is not None, "no settlement marker for the resolved fill"
            assert marker.state == STATE_COMPLETE, (
                f"the resolved fill did not settle, state={marker.state}"
            )
            txn = await ledger_transaction_for_fill(session, FILL_ID)
            assert txn is not None, "no ledger posting for the resolved fill"

            position = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == local.symbol
                    )
                )
            ).scalar_one()
            assert Decimal(str(position.quantity)) == Decimal("1"), (
                f"projection is {position.quantity}, expected the full 1 after both fills"
            )

            plans = (await session.execute(select(TradePlanORM))).scalars().all()
            assert any(p.state == "ACTIVE" for p in plans), (
                "the resolved entry did not converge a plan to ACTIVE"
            )
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_duplicate_and_restart_after_resolution_duplicate_nothing(database):
    """A second identical event and a restart must not duplicate any effect."""
    engine, adapter, _, _, _, _ = await _open_long_position(
        database, quantity="1", ask_quantity="0.4"
    )
    try:
        entry = next(iter(adapter.orders.values()))
        local = await engine.order_manager.get_by_client(entry.client_order_id)
        assert local is not None
        client_order_id, venue_id = await _clear_venue_id(
            database, local.internal_order_id
        )

        for n in (1, 2):
            await engine._enqueue_event(
                _fill_event(
                    event_id=f"evt-dup-{n}",
                    client_order_id=client_order_id,
                    symbol=local.symbol,
                    fill_id=DUP_FILL_ID,
                    venue_id=venue_id,
                )
            )
            await engine.wait_for_event_queue()

        before = await _counts(database)
        assert before["ledger_for_fill"] == 1, (
            "the resolved fill must have exactly one ledger posting, "
            f"got {before['ledger_for_fill']}"
        )
        async with database.session_factory() as session:
            row = await session.get(OrderORM, local.internal_order_id)
        assert Decimal(str(row.filled_quantity)) == Decimal("1"), (
            "the duplicate event applied the quantity twice"
        )
    finally:
        await engine.stop()

    restarted = make_paper_engine(database, engine_tick_seconds=3600)
    await restarted.start("run-evi-restart")
    try:
        after = await _counts(database)
        assert after["fills"] == before["fills"], "restart duplicated a fill"
        assert after["ledger"] == before["ledger"], "restart duplicated a ledger posting"
        assert after["ledger_for_fill"] == 1, "the fill gained a second ledger posting"
        assert after["positions"] == before["positions"], "restart duplicated a position"
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_event_without_a_venue_id_is_dropped_not_applied(database):
    """Documented LIMIT of the fallback, asserted so it cannot change silently.

    ``process_exchange_event`` returns early when the payload carries no
    ``exchange_order_id``: the client-id fallback is reachable only when the event
    NAMES a venue id the engine has not persisted yet. A payload with no venue id
    at all is dropped WITHOUT an identity anomaly - so it is not a data-loss path
    that a replayed unambiguous event would miss, but it is also not resolved.

    Stated rather than glossed: this is the boundary of what the fix covers.
    """
    from crypto_trader.domain.models import ExchangeEvent as _E

    engine, adapter, _, _, _, _ = await _open_long_position(
        database, quantity="1", ask_quantity="0.4"
    )
    try:
        entry = next(iter(adapter.orders.values()))
        local = await engine.order_manager.get_by_client(entry.client_order_id)
        client_order_id, _ = await _clear_venue_id(database, local.internal_order_id)

        await engine._enqueue_event(
            _E(
                event_id="evt-no-venue-id",
                event_type=ExchangeEventType.ORDER_FILLED,
                symbol=local.symbol,
                timestamp=datetime.now(UTC),
                payload={
                    "client_order_id": client_order_id,
                    "fill_id": "fill-no-venue",
                    "fill_price": "100.05",
                    "fill_quantity": REMAINING,
                    "fee": "0.01",
                },
            )
        )
        await engine.wait_for_event_queue()

        async with database.session_factory() as session:
            fill = (
                await session.execute(
                    select(FillORM).where(FillORM.fill_id == "fill-no-venue")
                )
            ).scalar_one_or_none()
        assert fill is None, (
            "an event naming no venue id was applied anyway - the fallback boundary "
            "changed; re-evaluate whether that is intended"
        )
    finally:
        await engine.stop()
