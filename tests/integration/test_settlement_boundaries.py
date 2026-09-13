"""P0-3.1 boundaries: the concurrency path and the global COMPLETE invariant.

Two gaps this closes:

  1. ``apply_fill``'s IntegrityError branch (two transactions inserting the same
     fill_id concurrently) returned WITHOUT creating the settlement marker or
     driving settlement, so a fill that lost the race could stay half-settled
     forever - while the sequential duplicate path healed correctly. Identical
     situations must behave identically.

  2. A COMPLETE marker was never re-validated. ``pending_settlements`` excludes
     COMPLETE rows by design, so a COMPLETE that contradicts the ledger or a
     closed lifecycle would be skipped forever. The invariant is now checked
     globally, and BEFORE the pending scan, so it cannot hide.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.domain.enums import OrderSide, OrderType, TimeInForce, TradingMode
from crypto_trader.domain.models import Fill, OrderIntent
from crypto_trader.order.manager import OrderManager
from crypto_trader.order.settlement import (
    STATE_COMPLETE,
    SettlementStateContradiction,
)
from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
    TradeEpisodeORM,
    TradePlanORM,
)

SYMBOL = "BTCUSDT"


def _intent(client="c_boundary"):
    return OrderIntent(
        client_order_id=client,
        symbol=SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="100",
        quantity="1",
    )


def _fill(order, *, fill_id="fill_race", qty="0.4"):
    return Fill(
        fill_id=fill_id,
        order_id=order.internal_order_id,
        client_order_id=order.client_order_id,
        exchange_order_id=order.exchange_order_id,
        symbol=order.symbol,
        side=order.side,
        price=Decimal("100"),
        quantity=Decimal(qty),
        fee=Decimal("0.01"),
        fee_currency="USDT",
        timestamp=datetime.now(UTC),
    )


async def _acknowledged_order(mgr):
    order = await mgr.create_from_intent(_intent(), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.ack(order.internal_order_id, "ex_race")
    await mgr.opened(order.internal_order_id)
    return await mgr.get(order.internal_order_id)


# ------------------------------------------------------ §1 IntegrityError race


@pytest.mark.asyncio
async def test_integrity_race_converges_like_a_normal_duplicate(database):
    """Two CONCURRENT apply_fill calls for one fill_id must converge.

    Whichever loses the INSERT race must still create the durable marker and
    drive settlement, exactly like the sequential duplicate path.
    """
    settlements: list[str] = []

    async def settle(fill):
        settlements.append(fill.fill_id)

    mgr = OrderManager(database.session_factory, settlement_callback=settle)
    order = await _acknowledged_order(mgr)
    fill = _fill(order)

    # Launch both coroutines and let them interleave: both read "no existing
    # fill", both attempt the INSERT, and one hits the unique constraint.
    results = await asyncio.gather(
        mgr.apply_fill(fill), mgr.apply_fill(fill), return_exceptions=True
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"a concurrent apply_fill raised: {errors}"
    newly = [r[2] for r in results]
    assert sorted(newly) == [False, True], f"expected one winner, got {newly}"

    async with database.session_factory() as session:
        fills = (await session.execute(select(FillORM))).scalars().all()
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill.fill_id)
            )
        ).scalar_one_or_none()
        ledger_count = (
            await session.execute(
                select(func.count())
                .select_from(LedgerTransactionORM)
                .where(LedgerTransactionORM.fill_id == fill.fill_id)
            )
        ).scalar_one()
    restored = await mgr.get(order.internal_order_id)

    assert len(list(fills)) == 1, "the race duplicated the fill"
    assert restored.filled_quantity == Decimal("0.4"), (
        "the race applied the quantity twice"
    )
    assert marker is not None, "the race path created no settlement marker"
    assert ledger_count <= 1
    assert settlements, "the race path never drove settlement"
    assert fill.fill_id in settlements


# ------------------------------------- §2/§3 global COMPLETE consistency


async def _make_complete_marker(database, fill_id, order_id):
    async with database.session_factory() as session:
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
            )
        ).scalar_one_or_none()
        if marker is None:
            marker = FillSettlementORM(
                fill_id=fill_id,
                order_id=order_id,
                symbol=SYMBOL,
                state=STATE_COMPLETE,
                attempt_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(marker)
        else:
            marker.state = STATE_COMPLETE
        await session.commit()


@pytest.mark.asyncio
async def test_COMPLETE_closed_plan_without_episode_fails_closed(database):
    """§3: COMPLETE + plan CLOSED + no episode is a contradiction."""
    from crypto_trader.order.settlement import assert_complete_settlements_consistent

    mgr = OrderManager(database.session_factory)
    order = await _acknowledged_order(mgr)
    fill = _fill(order, fill_id="fill_closed_no_episode")
    async with database.session_factory() as session:
        session.add(
            FillORM(
                fill_id=fill.fill_id,
                order_id=order.internal_order_id,
                symbol=SYMBOL,
                side=OrderSide.BUY.value,
                price=Decimal("100"),
                quantity=Decimal("0.4"),
                fee=Decimal("0.01"),
                timestamp=fill.timestamp,
            )
        )
        session.add(
            LedgerTransactionORM(
                transaction_id="txn_closed_no_episode",
                entry_type="TRADE",
                account_id="default",
                fill_id=fill.fill_id,
                order_id=order.internal_order_id,
                created_at=datetime.now(UTC),
                ownership_status="OWNED",
            )
        )
        await session.commit()

    # Point the order at a CLOSED plan that has no episode.
    async with database.session_factory() as session:
        row = await session.get(
            __import__(
                "crypto_trader.persistence.models", fromlist=["OrderORM"]
            ).OrderORM,
            order.internal_order_id,
        )
        row.metadata_json = {"trade_plan_id": "plan_closed_no_episode"}
        session.add(
            TradePlanORM(
                trade_plan_id="plan_closed_no_episode",
                symbol=SYMBOL,
                direction="LONG",
                state="CLOSED",
                decision_id="d1",
                requested_quantity=Decimal("1"),
            )
        )
        await session.commit()

    await _make_complete_marker(database, fill.fill_id, order.internal_order_id)
    async with database.session_factory() as session:
        marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == fill.fill_id)
            )
        ).scalar_one()
        marker.ledger_transaction_id = "txn_closed_no_episode"
        await session.commit()

    async with database.session_factory() as session:
        episodes = (
            await session.execute(
                select(TradeEpisodeORM).where(
                    TradeEpisodeORM.trade_plan_id == "plan_closed_no_episode"
                )
            )
        ).scalars().all()
        assert list(episodes) == [], "precondition: no episode exists"

        with pytest.raises(SettlementStateContradiction):
            await assert_complete_settlements_consistent(session)


@pytest.mark.asyncio
async def test_race_path_is_actually_exercised(database):
    """Instrument that the IntegrityError path really runs.

    ``commit`` is wrapped so we can see the unique-constraint loss directly; a
    test that merely runs two sequential calls would prove nothing about the race
    branch, so this asserts the branch was reached.
    """
    hits = {"integrity": 0}
    settlements: list[str] = []

    async def settle(fill):
        settlements.append(fill.fill_id)

    mgr = OrderManager(database.session_factory, settlement_callback=settle)
    order = await _acknowledged_order(mgr)
    fill = _fill(order, fill_id="fill_race_probe")

    import sqlalchemy.exc as sa_exc

    original = sa_exc.IntegrityError
    try:
        # Count how often the constraint actually fires.
        class _Counting(original):  # type: ignore[misc, valid-type]
            def __init__(self, *a, **kw):
                hits["integrity"] += 1
                super().__init__(*a, **kw)

        sa_exc.IntegrityError = _Counting
        import crypto_trader.order.manager as _mgr_mod

        _mgr_mod.IntegrityError = _Counting
        results = await asyncio.gather(
            mgr.apply_fill(fill), mgr.apply_fill(fill), return_exceptions=True
        )
    finally:
        sa_exc.IntegrityError = original
        _mgr_mod.IntegrityError = original

    assert not [r for r in results if isinstance(r, Exception)]
    assert hits["integrity"] >= 1, (
        "the concurrent INSERT never lost the race, so the race branch was not "
        "exercised - increase the interleaving or this test proves nothing"
    )
    assert settlements, "the race path drove no settlement"


# ------------------------------------- §6/§7 startup detects corrupted COMPLETE


async def _seed_entry_and_corrupt(database, *, drop_ledger: bool, closed_without_episode: bool):
    """Drive a real entry, then corrupt the COMPLETE invariant, then stop."""
    from tests.integration.test_settlement_recovery import _await_fill, _engine, _open_entry

    engine = _engine(database)
    await engine.start("run-boundary-seed")
    await _open_entry(database, engine)
    fills = await _await_fill(database)
    fill = fills[0]
    await engine._ensure_fill_settled(fill.fill_id)
    await engine.stop()

    async with database.session_factory() as session:
        if drop_ledger:
            await session.delete(
                (
                    await session.execute(
                        select(LedgerTransactionORM).where(
                            LedgerTransactionORM.fill_id == fill.fill_id
                        )
                    )
                ).scalar_one()
            )
        if closed_without_episode:
            from crypto_trader.persistence.models import OrderORM

            order = (
                await session.execute(
                    select(OrderORM).where(OrderORM.internal_order_id == fill.order_id)
                )
            ).scalar_one()
            trade_plan_id = str((order.metadata_json or {}).get("trade_plan_id") or "")
            plan = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == trade_plan_id)
                )
            ).scalar_one()
            plan.state = "CLOSED"
            for episode in (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.trade_plan_id == trade_plan_id
                    )
                )
            ).scalars().all():
                await session.delete(episode)
        await session.commit()
    return fill.fill_id


@pytest.mark.asyncio
async def test_startup_detects_COMPLETE_without_ledger(database):
    """§6: a fresh engine must refuse to start on a corrupted COMPLETE."""
    from crypto_trader.order.settlement import SettlementStateContradiction
    from tests.integration.test_settlement_recovery import _engine

    await _seed_entry_and_corrupt(database, drop_ledger=True, closed_without_episode=False)

    engine = _engine(database)
    with pytest.raises(SettlementStateContradiction):
        await engine.start("run-boundary-detect-1")

    health = engine.health.snapshot()["components"].get("fill_settlement")
    assert health is not None and health["ok"] is False, (
        "a failed settlement scan must mark fill_settlement unhealthy"
    )


@pytest.mark.asyncio
async def test_startup_detects_COMPLETE_without_episode(database):
    """§7: a closed lifecycle claiming COMPLETE with no episode must fail closed."""
    from crypto_trader.order.settlement import SettlementStateContradiction
    from tests.integration.test_settlement_recovery import _engine

    await _seed_entry_and_corrupt(
        database, drop_ledger=False, closed_without_episode=True
    )

    engine = _engine(database)
    with pytest.raises(SettlementStateContradiction):
        await engine.start("run-boundary-detect-2")

    health = engine.health.snapshot()["components"].get("fill_settlement")
    assert health is not None and health["ok"] is False
