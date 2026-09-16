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
    # H4 canonical status; legacy_status keeps the pre-closure name.
    assert result["status"] == "MATCH"
    assert result["legacy_status"] == "MATCHED"
    assert result["leg_execution_safe"] is True
    assert result["is_order"] is False
    assert result["authority"] == "RECONCILIATION_ONLY"


async def test_untracked_net_position_is_flagged(database) -> None:
    service = PositionLegService(database.session_factory)
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.5"))
    # OLD status name: UNTRACKED_NET_POSITION. NEW canonical: AGGREGATE_MISMATCH.
    assert result["status"] == "AGGREGATE_MISMATCH"
    assert result["legacy_status"] == "UNTRACKED_NET_POSITION"
    assert result["leg_execution_safe"] is False


async def test_divergence_between_legs_and_net_is_flagged(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.4"))
    # OLD status name: DIVERGED. NEW canonical: AGGREGATE_MISMATCH.
    assert result["status"] == "AGGREGATE_MISMATCH"
    assert result["legacy_status"] == "DIVERGED"
    assert result["computed_net"] == Decimal("1.00000000")
    assert result["difference"] == Decimal("-0.60000000")


async def test_matching_legs_and_net_are_safe_for_hedge_execution(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    await service.apply_order_fill("leg-long", OrderSide.SELL, Decimal("0.25"))
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.75"))
    assert result["status"] == "MATCH"
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


async def test_restart_keeps_leg_reconciliation_gate_fail_closed(database) -> None:
    """After a process restart the hedge gate must still trust factual reconciliation."""
    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM
    from tests.conftest import make_paper_engine
    from tests.low_risk.test_phase4_runtime_deterministic_exit import _open_v2_position

    engine_a = make_paper_engine(database, engine_tick_seconds=3600)
    await engine_a.start("run-restart-a")
    assert await engine_a._strategy_context("BTCUSDT") is not None
    await _open_v2_position(engine_a, database)
    await engine_a.wait_for_event_queue()
    factual_position = await engine_a.portfolio.get_position("BTCUSDT")
    assert factual_position is not None and factual_position.quantity > 0
    await engine_a.stop()

    # New process: same DB, same canonical services, fresh in-memory state.
    engine_b = make_paper_engine(database, engine_tick_seconds=3600)
    await engine_b.start("run-restart-b")
    restored = await engine_b.portfolio.get_position("BTCUSDT")
    assert restored is not None and restored.quantity == factual_position.quantity
    service = PositionLegService(database.session_factory)
    engine_b.leg_service = service
    engine_b.leg_reconciler = LegPositionReconciler(service)

    # The deterministic deposit has no leg rows, so legs cannot yet be the
    # source of truth: the gate reports the net position as untracked.
    reconciliation = await engine_b.leg_reconciler.reconcile("BTCUSDT", restored.quantity)
    assert reconciliation["leg_execution_safe"] is False

    # Even with leg execution switched on, hedge submission stays blocked.
    engine_b.leg_execution_enabled = True
    signal = await _hedge_signal()
    assert await engine_b.process_signal(signal) is None
    async with database.session_factory() as session:
        actions = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    assert "HEDGE_EXECUTION_BLOCKED_LEG_DIVERGENCE" in actions
    await engine_b.stop()


async def test_open_legs_for_symbol_exposes_only_unclosed_legs(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    open_legs = await service.open_legs_for_symbol("BTCUSDT")
    assert [(leg["leg_id"], leg["side"]) for leg in open_legs] == [("leg-long", "LONG")]
    assert open_legs[0]["remaining_quantity"] == Decimal("1")

    # A fully closed leg disappears from the deterministic-exit resolver.
    await service.apply_order_fill("leg-long", OrderSide.SELL, Decimal("1"))
    assert await service.open_legs_for_symbol("BTCUSDT") == []


async def test_deterministic_exit_resolves_persisted_leg_key(database) -> None:
    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM
    from tests.conftest import make_paper_engine
    from tests.low_risk.test_phase4_runtime_deterministic_exit import _open_v2_position

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-det-exit-leg-key")
    assert await engine._strategy_context("BTCUSDT") is not None
    await _open_v2_position(engine, database)
    await engine.wait_for_event_queue()

    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is not None and position.quantity > 0
    service = PositionLegService(database.session_factory)
    await service.register(LONG, trade_plan_id="plan-long", quantity=position.quantity)
    engine.leg_service = service

    ctx = await engine._strategy_context("BTCUSDT")
    await engine._deterministic_exit_signals(ctx, position)

    async with database.session_factory() as session:
        rows = (await session.execute(select(AuditEventORM))).scalars().all()
    keys = [row for row in rows if row.action == "DETERMINISTIC_EXIT_LEG_KEY"]
    assert keys, "deterministic exit must record its leg-key resolution"
    payload = keys[-1].after_json
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)
    assert payload["mode"] == "PERSISTED_LEG"
    assert keys[-1].target == "leg-long"
    await engine.stop()
