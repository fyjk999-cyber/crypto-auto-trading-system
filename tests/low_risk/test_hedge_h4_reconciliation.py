"""H4 leg reconciliation / restart recovery tests (HEDGE final closure)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    LegPositionReconciler,
    PositionLegService,
)
from tests.conftest import make_paper_engine

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation over 105",
    base_exit={"type": "PRICE", "trigger": "<=99"},
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
    base_exit={"type": "PRICE", "trigger": ">=111"},
    invalidation="acceptance above 115",
    evidence_families=["mean_reversion"],
    reason="independent reversal thesis",
)


async def _two_open_legs(database) -> PositionLegService:
    service = PositionLegService(database.session_factory)
    assert (await service.register(LONG)).allowed is True
    assert (await service.register(SHORT)).allowed is True
    await service.allocate_fill(
        fill_id="h4-long",
        leg_id="leg-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    await service.allocate_fill(
        fill_id="h4-short",
        leg_id="leg-short",
        side="SELL",
        price=Decimal("102"),
        quantity=Decimal("1"),
    )
    return service


async def test_net_zero_still_reports_gross_leg_risk(database) -> None:
    service = await _two_open_legs(database)
    report = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0"))
    assert report["status"] == "MATCH"
    assert report["leg_execution_safe"] is True
    assert report["leg_long"] == Decimal("1")
    assert report["leg_short"] == Decimal("1")
    assert report["computed_net"] == Decimal("0")
    assert report["gross"] == Decimal("2")
    assert report["both_sides"] is True
    assert report["open_leg_count"] == 2
    assert all(report["checks"].values())


async def test_pending_and_unknown_orders_fail_safe(database) -> None:
    from crypto_trader.persistence.models import OrderORM

    service = await _two_open_legs(database)
    await service.record_leg_order(
        leg_id="leg-long",
        client_order_id="coid-h4-pending",
        side="BUY",
        intended_quantity=Decimal("1"),
    )
    now = datetime.now(UTC)
    async with database.session_factory() as session:
        row = OrderORM(
            internal_order_id="ord-h4-pending",
            client_order_id="coid-h4-pending",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            quantity=Decimal("1"),
            status="SUBMITTED",
            trading_mode="PAPER",
            strategy_id="live_llm",
            created_at=now,
            updated_at=now,
            metadata_json={"leg_id": "leg-long"},
        )
        session.add(row)
        await session.commit()

    reconciler = LegPositionReconciler(service)
    pending = await reconciler.reconcile("BTCUSDT", Decimal("0"))
    assert pending["status"] == "PENDING_ORDER"
    assert pending["leg_execution_safe"] is False

    async with database.session_factory() as session:
        row = await session.get(OrderORM, "ord-h4-pending")
        row.status = "UNKNOWN"
        await session.commit()
    unknown = await reconciler.reconcile("BTCUSDT", Decimal("0"))
    assert unknown["status"] == "UNKNOWN"
    assert unknown["leg_execution_safe"] is False
    assert unknown["checks"]["no_unknown_orders"] is False


async def test_orphan_fill_is_detected(database) -> None:
    from crypto_trader.persistence.models import FillORM

    service = await _two_open_legs(database)
    now = datetime.now(UTC)
    async with database.session_factory() as session:
        session.add(
            FillORM(
                fill_id="fill-h4-orphan",
                order_id="ord-missing",
                client_order_id="coid-orphan",
                exchange_order_id="ex-orphan",
                symbol="BTCUSDT",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("0.3"),
                timestamp=now,
            )
        )
        await session.commit()
    report = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0"))
    assert report["status"] == "ORPHAN_FILL"
    assert report["leg_execution_safe"] is False
    assert report["orphan_fills"][0]["fill_id"] == "fill-h4-orphan"


async def test_leg_quantity_mismatch_is_detected(database) -> None:
    from crypto_trader.persistence.models import PositionLegORM

    service = await _two_open_legs(database)
    async with database.session_factory() as session:
        row = await session.get(PositionLegORM, "leg-long")
        row.quantity = Decimal("0.5")  # tampered opened quantity vs allocated fills
        await session.commit()
    report = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0"))
    assert report["status"] == "LEG_QUANTITY_MISMATCH"
    assert report["checks"]["leg_quantity_ok"] is False


async def test_restart_reconstructs_both_legs_and_keeps_closed_leg_closed(database) -> None:
    service = await _two_open_legs(database)
    await service.allocate_fill(
        fill_id="h4-close-long",
        leg_id="leg-long",
        side="SELL",
        price=Decimal("99"),
        quantity=Decimal("1"),
        terminal_reason="BASE_EXIT",
    )

    # "process restart": fresh service + reconciler over the same durable rows.
    restarted = PositionLegService(database.session_factory)
    legs = await restarted.all_legs_for_symbol("BTCUSDT")
    by_id = {leg["leg_id"]: leg for leg in legs}
    assert by_id["leg-long"]["state"] == "CLOSED"
    assert by_id["leg-long"]["terminal_reason"] == "BASE_EXIT"
    assert by_id["leg-short"]["state"] == "OPEN"
    assert by_id["leg-short"]["remaining_quantity"] == Decimal("1")

    report = await LegPositionReconciler(restarted).reconcile(
        "BTCUSDT", Decimal("-1"), after_restart=True
    )
    assert report["status"] == "RECOVERED"
    assert report["leg_execution_safe"] is True
    assert report["open_leg_count"] == 1
    assert report["closed_leg_count"] == 1

    # Duplicate delivery of the already-applied close fill is a no-op.
    duplicate = await restarted.allocate_fill(
        fill_id="h4-close-long",
        leg_id="leg-long",
        side="SELL",
        price=Decimal("99"),
        quantity=Decimal("1"),
    )
    assert duplicate["duplicate"] is True
    assert (await restarted.snapshot_state("leg-long"))["remaining_quantity"] == Decimal("0")


async def test_fully_closed_symbol_reports_closed(database) -> None:
    service = await _two_open_legs(database)
    await service.allocate_fill(
        fill_id="h4-close-both-l",
        leg_id="leg-long",
        side="SELL",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    await service.allocate_fill(
        fill_id="h4-close-both-s",
        leg_id="leg-short",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    report = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0"))
    assert report["status"] == "CLOSED"
    assert report["open_leg_count"] == 0
    assert report["leg_execution_safe"] is True


async def test_recovery_halts_on_leg_quantity_mismatch(database) -> None:
    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM, PositionLegORM

    await _two_open_legs(database)
    async with database.session_factory() as session:
        row = await session.get(PositionLegORM, "leg-long")
        row.quantity = Decimal("0.5")
        await session.commit()

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    engine.leg_reconciler = LegPositionReconciler(engine.leg_service)
    await engine.start("run-h4-recovery-halt")
    actions = await engine._run_recovery("run-h4-recovery-halt")
    assert "LEG_RECONCILIATION_HALTED" in actions
    assert engine.reconciliation_halted is True
    assert engine.health.snapshot()["components"]["leg_reconciliation"]["ok"] is False
    async with database.session_factory() as session:
        events = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    assert "LEG_RECONCILIATION_HALTED" in events
    await engine.stop()
