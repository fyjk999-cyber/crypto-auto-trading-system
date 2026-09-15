"""§16: the factual order lifecycle must be reconstructable after the fact.

first_fill_at / last_fill_at / cancel_requested_at / cancel_confirmed_at are
recorded inside the SAME transactions that already persist order status, and are
never read on a decision path. These tests use the real OrderManager API, not a
private helper, so they exercise the actual transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.domain.enums import TradingMode
from crypto_trader.domain.models import Fill
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.models import OrderORM

pytestmark = pytest.mark.asyncio


async def _make_order(manager: OrderManager, order_id: str = "ord-life"):
    from crypto_trader.domain.models import OrderIntent

    order = await manager.create_from_intent(
        OrderIntent(
            client_order_id=f"coid-{order_id}",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("10"),
            price=Decimal("100"),
        ),
        trading_mode=TradingMode.PAPER,
    )
    return order


async def _row(database, order_id: str) -> OrderORM:
    async with database.session_factory() as s:
        return (
            await s.execute(select(OrderORM).where(OrderORM.internal_order_id == order_id))
        ).scalar_one()


async def test_first_fill_at_is_set_once_and_last_fill_at_advances(database):
    """first_fill_at answers "immediate or resting?" - so it must NOT move."""
    manager = OrderManager(database.session_factory)
    order = await _make_order(manager)
    oid = order.internal_order_id
    await manager.validate(oid)
    await manager.submitting(oid)
    await manager.submitted(oid)

    t1 = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 14, 10, 0, 3, tzinfo=UTC)
    t3 = datetime(2026, 9, 14, 10, 0, 9, tzinfo=UTC)
    for ts, qty in ((t1, "2"), (t2, "3"), (t3, "1")):
        await manager.apply_fill(
            Fill(
                fill_id=f"fill-{ts.timestamp()}", order_id=oid, symbol="BTCUSDT",
                side="BUY", price=Decimal("100"), quantity=Decimal(qty), timestamp=ts,
            )
        )
    row = await _row(database, oid)
    assert row.first_fill_at is not None and row.first_fill_at.replace(tzinfo=UTC) == t1
    assert row.last_fill_at is not None and row.last_fill_at.replace(tzinfo=UTC) == t3


async def test_no_fill_leaves_fill_instants_empty(database):
    """UNKNOWN is not the same fact as "filled at zero"."""
    manager = OrderManager(database.session_factory)
    order = await _make_order(manager)
    row = await _row(database, order.internal_order_id)
    assert row.first_fill_at is None
    assert row.last_fill_at is None


async def test_cancel_requested_and_confirmed_are_separate_facts(database):
    """A requested-but-unconfirmed cancel is NOT a cancelled order."""
    manager = OrderManager(database.session_factory)
    order = await _make_order(manager)
    oid = order.internal_order_id
    await manager.validate(oid)
    await manager.submitting(oid)
    await manager.submitted(oid)
    await manager.ack(oid, "EX-1")

    await manager.cancel_pending(oid, "ENTRY_ORDER_TTL_EXPIRED")
    row = await _row(database, oid)
    assert row.cancel_requested_at is not None      # asked for
    assert row.cancel_confirmed_at is None          # not yet a fact

    await manager.cancel_confirm(oid)
    row = await _row(database, oid)
    assert row.cancel_confirmed_at is not None


async def test_cancel_confirmed_without_a_pending_request_still_records_both(database):
    """A venue-initiated cancel needs no local request; the request instant is
    then the confirmation instant rather than NULL."""
    manager = OrderManager(database.session_factory)
    order = await _make_order(manager)
    oid = order.internal_order_id
    await manager.validate(oid)
    await manager.submitting(oid)
    await manager.submitted(oid)
    await manager.ack(oid, "EX-2")

    await manager.cancel_confirm(oid)
    row = await _row(database, oid)
    assert row.cancel_requested_at is not None
    assert row.cancel_confirmed_at is not None


async def test_rejected_order_touches_no_cancel_instant(database):
    manager = OrderManager(database.session_factory)
    order = await _make_order(manager)
    oid = order.internal_order_id
    await manager.reject(oid, "MARKET_DATA_UNAVAILABLE")
    row = await _row(database, oid)
    assert row.cancel_requested_at is None
    assert row.cancel_confirmed_at is None
    assert row.first_fill_at is None
