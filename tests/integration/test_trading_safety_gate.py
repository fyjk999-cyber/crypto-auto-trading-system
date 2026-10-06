"""Actual planner/Risk/authority path; synthetic fixtures stay in tmp SQLite."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import event

from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.trade_plan.service import TradePlanService
from tests.conftest import make_paper_engine


async def test_actual_startup_and_stop_are_default_fail_closed(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    assert "EVENT_PROCESSING_NOT_HEALTHY" in engine.trading_safety_failures()
    assert "RUNTIME_NOT_RUNNING" in engine.trading_safety_failures()
    await engine.start("isolated-startup-safety")
    try:
        assert engine.trading_safety_failures() == ()
    finally:
        await engine.stop()
    assert "RUNTIME_NOT_RUNNING" in engine.trading_safety_failures()


@pytest.mark.parametrize("critical_component", ["event_processing", "reconciliation"])
@pytest.mark.parametrize("failure_boundary", ["before_tick", "during_market_read"])
async def test_critical_health_failure_blocks_actual_chief_provider_call(
    database, critical_component, failure_boundary
):
    from crypto_trader.llm_chief.engine import ChiefTraderEngine
    from crypto_trader.llm_chief.provider import LLMResponse
    from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
    from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
    from tests.integration.test_live_llm_position_lifecycle import Evidence

    class IsolatedProvider:
        calls = 0

        async def complete_json(self, **kwargs):
            self.calls += 1
            return LLMResponse(
                text="",
                provider="ISOLATED_FIXTURE",
                model="fixture",
                latency_ms=0,
                ok=False,
                error="LLM_UNAVAILABLE",
            )

    class ContextFailureAdapter(SimulatedExchangeAdapter):
        on_read = None

        async def get_orderbook(self, symbol, limit=100):
            book = await super().get_orderbook(symbol, limit)
            if self.on_read is not None:
                self.on_read()
            return book

    adapter = ContextFailureAdapter()
    engine = make_paper_engine(database, simulator=adapter, engine_tick_seconds=3600)
    await engine.start("isolated-before-chief-health")
    provider = IsolatedProvider()
    engine.strategies = [
        LiveLLMDecisionStrategy(
            evidence_engine=Evidence(),
            chief=ChiefTraderEngine(provider),
            planner=LiveLLMTradePlanner(engine.trade_plans),
            decisions=LLMDecisionStore(database.session_factory),
            audit=engine.audit,
        )
    ]
    try:
        fired = []

        def fail_health():
            fired.append(True)
            engine.health.set(critical_component, False, "isolated critical failure")

        if failure_boundary == "before_tick":
            fail_health()
        else:
            adapter.on_read = fail_health
        assert await engine.tick() == []
        assert fired
        assert provider.calls == 0
        assert await engine.order_manager.list_all() == []
        adapter.on_read = None
        engine.health.set(critical_component, True)
        assert engine.trading_safety_failures() == ()
        await engine.tick()
        assert provider.calls == 1  # Real Chief path is reachable when healthy.
    finally:
        await engine.stop()


@pytest.mark.parametrize(
    "worker_name,failure",
    [
        ("engine-events", "EVENT_WORKER_NOT_RUNNING"),
        ("engine-recon", "RECONCILIATION_WORKER_NOT_RUNNING"),
        ("engine-ticks", "TICK_WORKER_NOT_RUNNING"),
    ],
)
async def test_critical_worker_exit_cannot_reuse_old_healthy_flag(database, worker_name, failure):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("isolated-event-worker-exit")
    try:
        worker = next(t for t in engine._tasks if t.get_name() == worker_name)
        worker.cancel()  # Isolated worker only, not a production process.
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert failure in engine.trading_safety_failures()
    finally:
        await engine.stop()


@pytest.mark.parametrize(
    "failure_boundary", ["before_risk", "risk_insert", "order_lookup", "order_submitted"]
)
@pytest.mark.parametrize("failure_component", ["event_processing", "reconciliation"])
async def test_event_failure_after_risk_approval_prevents_actual_order(
    database, failure_boundary, failure_component
):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("isolated-p0-risk-boundary")
    engine.health.set("event_processing", True)
    assert await engine._strategy_context("BTCUSDT") is not None
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="fixture-chief-entry",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="isolated constitutional entry fixture",
        position_size_request=0.1,
        leverage_request=1,
        stop_loss=95,
        plan_contract_version=2,
        capital_allocation_pct=5.0,
        base_exit=BaseExitPlan(
            type="PRICE", trigger="110", size_pct=100.0, reason_code="BASE_EXIT"
        ),
        model_provider="deepseek",
        model="deepseek-flash",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="fixture")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101")
    )
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    fired = []
    risk_persisting = []
    if failure_boundary == "before_risk":
        engine.health.set(failure_component, False, "fixture queued-intent safety failure")
        fired.append(True)

    def fail_at_risk_durability(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO RISK_DECISIONS"):
            risk_persisting.append(True)
        fail_now = (
            (
                failure_boundary == "risk_insert"
                and statement.lstrip().upper().startswith("INSERT INTO RISK_DECISIONS")
            )
            or (
                failure_boundary == "order_lookup"
                and risk_persisting
                and statement.lstrip().upper().startswith("SELECT")
                and "FROM orders" in statement
            )
            or (
                failure_boundary == "order_submitted"
                and statement.lstrip().upper().startswith("INSERT INTO ORDER_EVENTS")
                and "ORDER_SUBMITTED" in parameters
            )
        )
        if fail_now:
            fired.append(True)
            engine.health.set(failure_component, False, "fixture critical safety failure")

    event.listen(database.engine.sync_engine, "before_cursor_execute", fail_at_risk_durability)
    try:
        risk = await engine.process_signal(signal)
        await engine.wait_for_event_queue()
        assert fired and risk.reason == "RISK_PASS"
        orders = await engine.order_manager.list_all()
        if failure_boundary == "order_submitted":
            # It was created while healthy; a later failure must prevent the
            # native PAPER acceptance/fill, not pretend creation never occurred.
            assert len(orders) == 1 and orders[0].status.value == "REJECTED"
        else:
            assert orders == []
        assert await engine.adapter.get_positions() == []
        event.remove(database.engine.sync_engine, "before_cursor_execute", fail_at_risk_durability)
        engine.health.set(failure_component, True, "fixture dependency recovered")
        # A previously rejected plan is terminal, not blindly replayed when
        # the dependency recovers. A fresh Chief decision would be required.
        assert await engine.process_signal(signal) is None
        assert len(await engine.order_manager.list_all()) == len(orders)
        assert await engine.adapter.get_positions() == []
    finally:
        if event.contains(
            database.engine.sync_engine, "before_cursor_execute", fail_at_risk_durability
        ):
            event.remove(
                database.engine.sync_engine, "before_cursor_execute", fail_at_risk_durability
            )
        await engine.stop()


async def _fresh_entry_signal(engine, decisions, plans, decision_id):
    entry = ChiefTraderDecision(
        decision_id=decision_id,
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="isolated constitutional entry fixture",
        position_size_request=0.1,
        leverage_request=1,
        stop_loss=95,
        plan_contract_version=2,
        capital_allocation_pct=5.0,
        base_exit=BaseExitPlan(
            type="PRICE", trigger="110", size_pct=100.0, reason_code="BASE_EXIT"
        ),
        model_provider="deepseek",
        model="deepseek-flash",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="fixture")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101")
    )
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    return plan, signal


async def test_kill_switch_and_health_gate_compose_without_bypass(database):
    from crypto_trader.trade_plan.service import TradePlanState

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("isolated-killswitch-health-composition")
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    try:
        assert await engine._strategy_context("BTCUSDT") is not None
        # 1. Kill switch alone blocks the risk-increasing entry.
        engine.risk_engine.kill_switch.engage("isolated-fixture")
        plan, signal = await _fresh_entry_signal(engine, decisions, plans, "fixture-ks")
        await engine.process_signal(signal)
        assert await engine.order_manager.list_all() == []
        assert (await plans.get(plan.trade_plan_id)).state in {
            TradePlanState.INVALIDATED,
            TradePlanState.REJECTED,
        }
        # 2. Disengaging the kill switch must not bypass invalid trading health.
        engine.risk_engine.kill_switch.disengage("isolated-fixture")
        engine.health.set("event_processing", False, "isolated fixture health failure")
        plan, signal = await _fresh_entry_signal(engine, decisions, plans, "fixture-health")
        await engine.process_signal(signal)
        assert await engine.order_manager.list_all() == []
        assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.INVALIDATED
        # 3. Healthy runtime + disengaged kill switch is the only executing case.
        engine.health.set("event_processing", True, "isolated fixture health restored")
        assert engine.trading_safety_failures() == ()
        plan, signal = await _fresh_entry_signal(engine, decisions, plans, "fixture-control")
        await engine.process_signal(signal)
        await engine.wait_for_event_queue()
        assert len(await engine.order_manager.list_all()) == 1
        audits = await engine.audit.list_recent(limit=200)
        assert any(
            audit.action in {"RISK_REJECT", "AUTHORITY_REJECT"}
            and "GLOBAL_KILL_SWITCH" in str(audit.after_json)
            for audit in audits
        )
        assert any(
            audit.action == "AUTHORITY_HOLD"
            and "TRADING_SAFETY_INVALID" in str(audit.after_json)
            for audit in audits
        )
    finally:
        await engine.stop()
