"""Phase 4D: leg-level reconciliation is the gate for hedge execution."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    LegPositionReconciler,
    PositionLegService,
)

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation",
    base_exit={"type": "PRICE", "trigger": ">=110"},
    invalidation="close below 98",
    evidence_families=["trend"],
    reason="momentum entry",
)


async def _seed(service: PositionLegService, *, quantity: Decimal) -> None:
    await service.register(LONG, trade_plan_id="plan-long", quantity=quantity)


async def test_no_leg_activity_with_flat_net_is_matched(database) -> None:
    service = PositionLegService(database.session_factory)
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0"))
    assert result["status"] == "MATCHED"
    assert result["leg_execution_safe"] is True
    assert result["is_order"] is False
    assert result["authority"] == "RECONCILIATION_ONLY"


async def test_untracked_net_position_is_flagged(database) -> None:
    service = PositionLegService(database.session_factory)
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.5"))
    assert result["status"] == "UNTRACKED_NET_POSITION"
    assert result["leg_execution_safe"] is False


async def test_divergence_between_legs_and_net_is_flagged(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.4"))
    assert result["status"] == "DIVERGED"
    assert result["computed_net"] == Decimal("1.00000000")
    assert result["difference"] == Decimal("-0.60000000")


async def test_matching_legs_and_net_are_safe_for_hedge_execution(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    await service.apply_order_fill("leg-long", OrderSide.SELL, Decimal("0.25"))
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.75"))
    assert result["status"] == "MATCHED"
    assert result["leg_execution_safe"] is True


async def _hedge_signal():
    from crypto_trader.domain.models import SignalIntent

    return SignalIntent(
        signal_id="hedge-gate-1",
        strategy_id="live_llm",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.1"),
        reason="independent hedge",
        metadata={
            "hedge": True,
            "lifecycle_action": "HEDGE",
            "leg_id": "leg-guard",
            "trade_plan_id": "plan-guard",
            "direction": "SHORT",
        },
    )


async def _audit_actions(engine, database):
    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM

    async with database.session_factory() as session:
        return [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]


async def test_enabled_hedge_requires_reconciler(database) -> None:
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_execution_enabled = True  # no reconciler injected
    await engine.start("run-hedge-no-reconciler")
    signal = await _hedge_signal()
    assert await engine.process_signal(signal) is None
    assert "HEDGE_EXECUTION_BLOCKED_NO_RECONCILER" in await _audit_actions(engine, database)
    await engine.stop()


async def test_enabled_hedge_blocks_on_leg_divergence(database) -> None:
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("0.5"))  # legs say LONG 0.5, net is FLAT
    engine.leg_service = service
    engine.leg_reconciler = LegPositionReconciler(service)
    engine.leg_execution_enabled = True
    await engine.start("run-hedge-divergence")
    signal = await _hedge_signal()
    assert await engine.process_signal(signal) is None
    assert "HEDGE_EXECUTION_BLOCKED_LEG_DIVERGENCE" in await _audit_actions(engine, database)
    await engine.stop()


async def test_enabled_hedge_passes_gate_when_reconciled(database) -> None:
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    service = PositionLegService(database.session_factory)
    engine.leg_service = service
    engine.leg_reconciler = LegPositionReconciler(service)
    engine.leg_execution_enabled = True  # flat net + no legs reconciles MATCHED
    await engine.start("run-hedge-reconciled")
    signal = await _hedge_signal()
    assert await engine.process_signal(signal) is None  # no plan yet
    actions = await _audit_actions(engine, database)
    assert "HEDGE_EXECUTION_BLOCKED_LEG_DIVERGENCE" not in actions
    assert "HEDGE_EXECUTION_BLOCKED_NO_RECONCILER" not in actions
    # The hedge gate itself passed; any later rejection is plan validation.
    assert any("PLAN" in action for action in actions)
    await engine.stop()
