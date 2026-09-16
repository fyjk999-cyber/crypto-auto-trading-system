"""PRE-ML convergence cross-subsystem constitutional tests.

These tests exist to prove that the four merged Low-Risk engineering lines
(Growth, Core Runtime, Hedge/PositionLeg, DeepSeek Flash High) compose without
granting execution authority to any deterministic or learning subsystem, and
without reintroducing a hard max-hold exit.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    PositionLegService,
)
from crypto_trader.llm_chief.failover import CoreLLMRouter
from crypto_trader.llm_chief.provider import DeepSeekProvider
from crypto_trader.persistence.models import AuditEventORM
from tests.conftest import make_paper_engine


async def _audit_actions(database) -> list[str]:
    async with database.session_factory() as session:
        rows = (await session.execute(select(AuditEventORM))).scalars().all()
    return [row.action for row in rows]


# ---------------------------------------------------------------------------
# Cross-subsystem authority test
# ---------------------------------------------------------------------------
def test_cross_subsystem_new_risk_authority_matrix() -> None:
    """Learning/Risk/FastProfit code paths carry no execution authority."""
    import crypto_trader.learning.growth_report as growth_report
    import crypto_trader.learning.growth_worker as growth_worker
    import crypto_trader.llm_chief.growth_context as growth_context
    import crypto_trader.risk.fast_profit as fast_profit
    from crypto_trader.risk.engine import RiskEngine

    order_authority_tokens = (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
    )
    for module in (growth_report, growth_worker, growth_context, fast_profit):
        source = inspect.getsource(module)
        for token in order_authority_tokens:
            assert token not in source, f"{module.__name__} must not reference {token}"

    # Risk check() is a gate, never an originator of an order path.
    risk_source = inspect.getsource(RiskEngine)
    for token in ("ExecutionAuthority", "OrderManager", "submit_order", "process_signal"):
        assert token not in risk_source, f"RiskEngine must not reference {token}"


async def test_non_core_origins_cannot_submit_entry_signal(database) -> None:
    """A model, Growth, or Risk signal is rejected by entry authority gate."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.enforce_llm_entry_authority = True
    await engine.start("run-authority-matrix")

    for origin in ("growth_memory", "quant_model", "risk_engine"):
        signal = SignalIntent(
            signal_id=f"sig-{origin}",
            strategy_id=origin,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
            reason="attempt to originate new risk",
            metadata={},
        )
        assert await engine.process_signal(signal) is None

    actions = await _audit_actions(database)
    assert actions.count("NON_LLM_DIRECTIONAL_AUTHORITY_REJECTED") >= 3
    assert await engine.order_manager.list_all(limit=20) == []
    await engine.stop()


# ---------------------------------------------------------------------------
# Cross-subsystem Hedge + Runtime test
# ---------------------------------------------------------------------------
async def test_hedge_and_runtime_keep_legs_independent(database) -> None:
    """Long risk exit must not collapse the independent short hedge leg."""
    long_leg = HedgeLegContract(
        leg_id="conv-long",
        symbol="BTCUSDT",
        side="LONG",
        kind=LegKind.ENTRY,
        strategy="BREAKOUT",
        thesis="breakout continuation",
        base_exit={"type": "PRICE", "trigger": "<=50"},
        invalidation="close below 98",
        evidence_families=["trend"],
        reason="momentum entry",
    )
    short_leg = HedgeLegContract(
        leg_id="conv-short",
        symbol="BTCUSDT",
        side="SHORT",
        kind=LegKind.HEDGE,
        strategy="MEAN_REVERT",
        thesis="independent range-rejection thesis",
        base_exit={"type": "PRICE", "trigger": ">=150"},
        invalidation="acceptance above 115",
        evidence_families=["mean_reversion"],
        reason="independent hedge",
    )
    service = PositionLegService(database.session_factory)
    assert (await service.register(long_leg)).allowed is True
    assert (await service.register(short_leg)).allowed is True
    await service.allocate_fill(
        fill_id="conv-long-fill",
        leg_id="conv-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    await service.allocate_fill(
        fill_id="conv-short-fill",
        leg_id="conv-short",
        side="SELL",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    await engine.start("run-convergence-hedge")

    from types import SimpleNamespace

    ctx = SimpleNamespace(
        mark_price=Decimal("94"),
        book=SimpleNamespace(mid_price=lambda: Decimal("94")),
        account=SimpleNamespace(equity=Decimal("10000")),
        realized_volatility=0.01,
    )
    signals, _ = await engine._leg_deterministic_exit_signals("BTCUSDT", ctx)
    assert [signal.metadata.get("leg_id") for signal, _ in signals] == ["conv-long"]
    signal = signals[0][0]
    assert signal.metadata["reduce_only"] is True
    assert signal.metadata["exit_authority"] == "RISK_HARD_EXIT"

    # The short leg is factual, protected and still open: no net collapse.
    open_legs = await service.open_legs_for_symbol("BTCUSDT")
    assert {leg["leg_id"] for leg in open_legs} == {"conv-long", "conv-short"}
    assert (await service.snapshot_state("conv-short"))["remaining_quantity"] == Decimal("1")
    assert (await service.snapshot_state("conv-long"))["remaining_quantity"] == Decimal("1")
    await engine.stop()


# ---------------------------------------------------------------------------
# Cross-subsystem Flash High + Offline test
# ---------------------------------------------------------------------------
async def test_flash_high_flat_offline_uses_same_model_recovery(database) -> None:
    """Provider outage -> offline -> flat health probe -> NORMAL, no trade."""
    state = {"healthy": False, "requests": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        state["requests"].append(payload)
        if not state["healthy"]:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"total_tokens": 5},
            },
        )

    provider = DeepSeekProvider(
        api_key="test-secret",
        model="deepseek-flash",
        transport=httpx.MockTransport(handler),
    )
    router = CoreLLMRouter(primary=provider, backup=None)
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.llm_router = router
    await engine.start("run-convergence-flash-offline")

    # Provider unavailable through the canonical router call.
    failed = await router.complete_json(prompt="canonical review", retries=0)
    assert failed.ok is False
    assert router.offline is True

    await engine.tick()
    assert engine.offline_mode.is_offline is True
    assert router.offline is True

    # Provider comes back while the runtime is FLAT. No position review exists,
    # so the engine's own probe must clear offline mode.
    state["healthy"] = True
    router.status.next_probe_at = datetime.now(UTC) - timedelta(seconds=1)
    engine.offline_mode.next_probe_at = datetime.now(UTC) - timedelta(seconds=1)
    await engine.tick()

    assert router.offline is False
    assert engine.offline_mode.is_offline is False
    actions = await _audit_actions(database)
    assert "LLM_OFFLINE_RECOVERY_PROBE" in actions
    assert "LLM_RECOVERED_NORMAL" in actions
    assert await engine.order_manager.list_all(limit=20) == []
    positions = await engine.portfolio.get_positions()
    assert not positions

    probe_requests = [r for r in state["requests"] if r.get("max_tokens") == 64]
    assert probe_requests, "provider health probe must use the canonical provider"
    assert all(r["model"] == "deepseek-flash" for r in state["requests"])
    legacy_models = {
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-pro",
        "deepseek-flash-high",
    }
    assert all(r["model"] not in legacy_models for r in state["requests"])
    await engine.stop()


async def test_convergence_diagnostics_ignore_generic_llm_model(monkeypatch) -> None:
    """Configured diagnostics use canonical model; effective follows response."""
    from crypto_trader.api.deps import LLMRuntimeStatus

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"runtime_health":"ok"}'}}]},
        )

    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    provider = DeepSeekProvider(
        api_key="test-secret",
        model="deepseek-flash",
        transport=httpx.MockTransport(handler),
    )
    router = CoreLLMRouter(primary=provider, backup=None)
    status = LLMRuntimeStatus(provider_instance=router)
    await status.probe()
    snapshot = status.snapshot()

    assert snapshot["provider"] == "deepseek"
    assert snapshot["model"] == "deepseek-flash"
    assert snapshot["effective_model"] == "deepseek-flash"
    assert snapshot["thinking"] is True
    assert snapshot["reasoning_effort"] == "high"
    assert "deepseek-v4-pro" not in json.dumps(snapshot)


async def test_core_llm_hedge_registers_independent_leg_without_reducing_long(database) -> None:
    """Core-LLM HEDGE opens an independent SHORT leg, never a reduce of LONG."""
    from types import SimpleNamespace

    from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision
    from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
    from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
    from crypto_trader.observability.audit import AuditService
    from crypto_trader.runtime.exit_controller import DeterministicExitController
    from crypto_trader.trade_plan.service import TradePlanService

    plans = TradePlanService(database.session_factory)
    service = PositionLegService(database.session_factory)
    manager = LiveLLMPositionManager(
        chief=SimpleNamespace(),
        evidence_engine=SimpleNamespace(),
        decisions=SimpleNamespace(),
        plans=plans,
        audit=AuditService(database.session_factory),
        hedge_planner=LiveLLMTradePlanner(plans),
        leg_service=service,
        base_exit_registry=DeterministicExitController().base_exits,
    )
    position = SimpleNamespace(symbol="BTCUSDT", quantity=Decimal("1"))
    plan = SimpleNamespace(trade_plan_id="tp-convergence-long")
    decision = ChiefTraderDecision(
        decision_id="conv-hedge-decision",
        symbol="BTCUSDT",
        position_state="OPEN",
        action="HEDGE",
        market_regime="TREND",
        strategy="MEAN_REVERT",
        thesis="independent range-rejection thesis, not loss mitigation",
        supporting_evidence=["mean_reversion"],
        position_size_request=0.5,
        leverage_request=1,
        plan_contract_version=2,
        capital_allocation_pct=5.0,
        base_exit=BaseExitPlan(
            type="PRICE", trigger="112", size_pct=100.0, reason_code="BASE_EXIT"
        ),
        thesis_invalidation="acceptance above 115",
    )
    ctx = SimpleNamespace(run_id="run-convergence-hedge-decision")

    signal = await manager._hedge_leg_signal(decision, plan, position, ctx)
    assert signal is not None
    assert signal.side is OrderSide.SELL  # the new SHORT hedge entry
    assert signal.metadata["hedge"] is True
    assert signal.metadata["lifecycle_action"] == "HEDGE"
    assert signal.metadata.get("reduce_only") is not True
    assert signal.metadata["base_exit"] is not None
    leg_id = signal.metadata["leg_id"]
    assert (await service.snapshot_state(leg_id))["side"] == "SHORT"

    await service.allocate_fill(
        fill_id="conv-hedge-fill",
        leg_id=leg_id,
        side="SELL",
        price=Decimal("107"),
        quantity=Decimal("0.5"),
    )
    open_legs = await service.open_legs_for_symbol("BTCUSDT")
    assert {(leg["side"], Decimal(str(leg["remaining_quantity"]))) for leg in open_legs} == {
        ("SHORT", Decimal("0.5"))
    }
    # The original LONG was not reduced or replaced by the hedge signal.
    assert position.quantity == Decimal("1")
