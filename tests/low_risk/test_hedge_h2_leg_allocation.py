"""H2 deterministic order/fill leg allocation tests (HEDGE final closure)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    PositionLegService,
)

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation over 105",
    base_exit={"type": "PRICE", "trigger": ">=110"},
    invalidation="close below 98",
    evidence_families=["trend"],
    reason="momentum entry",
)

SHORT = HedgeLegContract(
    leg_id="leg-short",
    symbol="BTCUSDT",
    side="SHORT",
    kind=LegKind.HEDGE,
    strategy="MEAN_REVERT",
    thesis="range rejection at 112 with exhaustion",
    base_exit={"type": "PRICE", "trigger": "<=104"},
    invalidation="acceptance above 115",
    evidence_families=["mean_reversion"],
    reason="independent reversal thesis",
)


async def test_partial_fills_allocate_to_intended_leg_only(database) -> None:
    service = PositionLegService(database.session_factory)
    assert (await service.register(LONG)).allowed is True
    assert (await service.register(SHORT)).allowed is True

    long_result = await service.allocate_fill(
        fill_id="fill-l1",
        leg_id="leg-long",
        side=OrderSide.BUY,
        price=Decimal("100"),
        quantity=Decimal("0.4"),
        fee=Decimal("0.01"),
    )
    short_result = await service.allocate_fill(
        fill_id="fill-s1",
        leg_id="leg-short",
        side=OrderSide.SELL,
        price=Decimal("102"),
        quantity=Decimal("0.5"),
        fee=Decimal("0.02"),
    )
    assert long_result["applied"] is True
    assert short_result["applied"] is True

    long_state = await service.snapshot_state("leg-long")
    short_state = await service.snapshot_state("leg-short")
    assert long_state["remaining_quantity"] == Decimal("0.4")
    assert long_state["average_entry_price"] == Decimal("100")
    assert short_state["remaining_quantity"] == Decimal("0.5")
    assert short_state["average_entry_price"] == Decimal("102")
    assert [f["fill_id"] for f in await service.leg_fills("leg-long")] == ["fill-l1"]
    assert [f["fill_id"] for f in await service.leg_fills("leg-short")] == ["fill-s1"]
    assert long_state["fees"] == Decimal("0.01")
    assert short_state["fees"] == Decimal("0.02")


async def test_duplicate_fill_never_double_applies(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    first = await service.allocate_fill(
        fill_id="fill-dup",
        leg_id="leg-long",
        side=OrderSide.BUY,
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    second = await service.allocate_fill(
        fill_id="fill-dup",
        leg_id="leg-long",
        side=OrderSide.BUY,
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    assert first["applied"] is True and first["duplicate"] is False
    assert second["applied"] is False and second["duplicate"] is True
    state = await service.snapshot_state("leg-long")
    assert state["remaining_quantity"] == Decimal("1")
    assert len(await service.leg_fills("leg-long")) == 1


async def test_record_leg_order_unique_and_unknown_blocks(database) -> None:
    from crypto_trader.persistence.models import OrderORM

    service = PositionLegService(database.session_factory)
    created = await service.record_leg_order(
        leg_id="leg-long",
        client_order_id="coid-leg-1",
        side="BUY",
        intended_quantity=Decimal("1"),
        trade_plan_id="plan-1",
        decision_id="dec-1",
        source_action="OPEN",
    )
    duplicate = await service.record_leg_order(
        leg_id="leg-long",
        client_order_id="coid-leg-1",
        side="BUY",
        intended_quantity=Decimal("1"),
    )
    assert created is True and duplicate is False

    now = datetime.now(UTC)
    async with database.session_factory() as session:
        session.add(
            OrderORM(
                internal_order_id="ord-unknown-1",
                client_order_id="coid-unknown-1",
                symbol="BTCUSDT",
                side="SELL",
                order_type="LIMIT",
                time_in_force="GTC",
                quantity=Decimal("1"),
                status="UNKNOWN",
                trading_mode="PAPER",
                strategy_id="live_llm",
                created_at=now,
                updated_at=now,
                metadata_json={"leg_id": "leg-long"},
            )
        )
        await session.commit()

    unknowns = await service.unresolved_unknowns("leg-long")
    assert [item["client_order_id"] for item in unknowns] == ["coid-unknown-1"]
    assert await service.unresolved_unknowns("leg-short") == []

    orders = await service.leg_orders("leg-long")
    assert orders[0]["client_order_id"] == "coid-leg-1"
    assert orders[0]["reduce_only"] is False


async def test_process_signal_requires_explicit_leg_target(database) -> None:
    from sqlalchemy import select

    from crypto_trader.domain.models import SignalIntent
    from crypto_trader.persistence.models import AuditEventORM
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-h2-leg-target")
    signal = SignalIntent(
        signal_id="add-missing-leg",
        strategy_id="live_llm_position",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.1"),
        reason="leg add",
        metadata={"lifecycle_action": "ADD"},
    )
    assert await engine.process_signal(signal) is None
    async with database.session_factory() as session:
        actions = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    assert "LEG_TARGET_REQUIRED" in actions
    await engine.stop()


async def test_process_signal_blocks_replacement_while_unknown_order_unresolved(database) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from crypto_trader.domain.models import SignalIntent
    from crypto_trader.persistence.models import AuditEventORM, OrderORM
    from tests.conftest import make_paper_engine

    now = datetime.now(UTC)
    async with database.session_factory() as session:
        session.add(
            OrderORM(
                internal_order_id="ord-h2-unknown",
                client_order_id="coid-h2-unknown",
                symbol="BTCUSDT",
                side="SELL",
                order_type="LIMIT",
                time_in_force="GTC",
                quantity=Decimal("1"),
                status="UNKNOWN",
                trading_mode="PAPER",
                strategy_id="live_llm",
                created_at=now,
                updated_at=now,
                metadata_json={"leg_id": "leg-unknown"},
            )
        )
        await session.commit()

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    await engine.start("run-h2-unknown-block")
    signal = SignalIntent(
        signal_id="add-while-unknown",
        strategy_id="live_llm_position",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.1"),
        reason="leg add",
        metadata={
            "lifecycle_action": "ADD",
            "leg_id": "leg-unknown",
            "trade_plan_id": "plan-unknown",
        },
    )
    assert await engine.process_signal(signal) is None
    async with database.session_factory() as session:
        actions = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    # Either the canonical unsettled-order guard or the leg-level UNKNOWN guard
    # may fire first; both prove no replacement exposure is created.
    assert {
        "LEG_ORDER_UNKNOWN_BLOCKS_REPLACEMENT",
        "POSITION_ACTION_BLOCKED_ENTRY_UNSETTLED",
    } & set(actions)
    await engine.stop()
