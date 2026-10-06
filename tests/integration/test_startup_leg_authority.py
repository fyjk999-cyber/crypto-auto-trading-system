"""Required leg failure cannot be erased by account-only reconciliation."""

from decimal import Decimal

import pytest

from crypto_trader.execution.hedge_legs import LegPositionReconciler, PositionLegService
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from tests.conftest import make_paper_engine
from tests.integration.test_trading_safety_gate import _fresh_entry_signal
from tests.low_risk.test_phase4d_leg_reconciliation import LONG


async def test_failed_leg_recovery_then_coherent_account_blocks_chief_entry(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    service = PositionLegService(database.session_factory)
    await service.register(LONG, trade_plan_id="fixture-divergent-leg", quantity=Decimal("1"))
    engine.leg_service = service
    engine.leg_reconciler = LegPositionReconciler(service)
    await engine.start("isolated-required-leg-startup")
    try:
        assert engine.reconciliation_current_state == "COHERENT_OK"
        assert "LEG_RECONCILIATION_NOT_HEALTHY" in engine.trading_safety_failures()
        _, signal = await _fresh_entry_signal(
            engine, LLMDecisionStore(database.session_factory), engine.trade_plans,
            "fixture-leg-failure-chief",
        )
        await engine.process_signal(signal)
        await engine.wait_for_event_queue()
        assert await engine.order_manager.list_all() == []
        assert await engine.adapter.get_positions() == []
        # Dropping a required dependency is not factual recovery of its failure.
        engine.leg_service = None
        engine.leg_reconciler = None
        assert "LEG_RECONCILIATION_NOT_HEALTHY" in engine.trading_safety_failures()
    finally:
        await engine.stop()


async def test_healthy_required_legs_and_account_allow_normal_chief_entry(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    engine.leg_reconciler = LegPositionReconciler(engine.leg_service)
    await engine.start("isolated-healthy-leg-control")
    try:
        assert engine.reconciliation_current_state == "COHERENT_OK"
        assert engine.trading_safety_failures() == ()
        assert await engine._strategy_context("BTCUSDT") is not None
        _, signal = await _fresh_entry_signal(
            engine, LLMDecisionStore(database.session_factory), engine.trade_plans,
            "fixture-healthy-leg-chief",
        )
        await engine.process_signal(signal)
        await engine.wait_for_event_queue()
        assert len(await engine.order_manager.list_all()) == 1
    finally:
        await engine.stop()


@pytest.mark.parametrize("status", ["NOT_RUN", "UNKNOWN", "FAILED"])
async def test_unaccepted_required_leg_state_blocks_risk(database, status):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    engine.leg_reconciler = LegPositionReconciler(engine.leg_service)
    await engine.start("isolated-leg-state-" + status)
    try:
        engine.health.set("leg_reconciliation", False, status)
        assert "LEG_RECONCILIATION_NOT_HEALTHY" in engine.trading_safety_failures()
        _, signal = await _fresh_entry_signal(
            engine, LLMDecisionStore(database.session_factory), engine.trade_plans,
            "fixture-leg-state-chief-" + status,
        )
        await engine.process_signal(signal)
        assert await engine.order_manager.list_all() == []
    finally:
        await engine.stop()
