"""Phase 4 offline-mode tests (SPEC OFFLINE RULE).

DeepSeek+GLM failure -> LLM_OFFLINE_MODE: new risk blocked, pending new-risk
orders cancelled, protective exits still run, five-minute probe windows, and
NORMAL only after factual reconciliation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import AuditEventORM
from crypto_trader.runtime.offline import OfflineMode
from crypto_trader.trade_plan.service import TradePlanService
from tests.conftest import make_paper_engine

BASE = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)


class _FakeOrder:
    def __init__(self, metadata: dict, strategy_id: str = "live_llm") -> None:
        self.metadata = metadata
        self.strategy_id = strategy_id
        self.internal_order_id = "ord1"
        self.client_order_id = "c1"
        self.exchange_order_id = None
        self.symbol = "BTCUSDT"


class _FakeRouter:
    def __init__(self, offline: bool = True) -> None:
        self.offline = offline

    def healthy(self) -> bool:
        return True

    def diagnostics(self) -> dict:
        return {"router": "fake", "offline": {"offline": self.offline}}


def test_offline_blocks_new_risk_but_allows_protective_exits() -> None:
    mode = OfflineMode()
    assert mode.allows_new_risk() is True
    assert mode.enter("ALL_PROVIDERS_FAILED", now=BASE) is True
    assert mode.enter("SECOND_CALL", now=BASE) is False  # idempotent

    assert mode.allows_new_risk() is False
    assert mode.blocks_new_risk({"lifecycle_action": "ADD"}, "live_llm") is True
    assert mode.blocks_new_risk({}, "live_llm") is True  # live_llm entry
    assert mode.blocks_new_risk({"reduce_only": True}, "live_llm_position") is False
    assert (
        mode.blocks_new_risk(
            {"exit_authority": "FAST_PROFIT_PROTECTION", "deterministic_exit": True}
        )
        is False
    )
    assert (
        mode.blocks_new_risk({"lifecycle_action": "RISK_HARD_EXIT", "reduce_only": True}) is False
    )
    snapshot = mode.snapshot()
    assert snapshot["offline"] is True
    assert snapshot["windows"] == 1
    assert snapshot["next_probe_at"] == (BASE + timedelta(seconds=300)).isoformat()


def test_pending_new_risk_filter_excludes_protective_orders() -> None:
    mode = OfflineMode()
    mode.enter("TEST", now=BASE)
    orders = [
        _FakeOrder({}, "live_llm"),
        _FakeOrder({"lifecycle_action": "ADD"}, "live_llm_position"),
        _FakeOrder({"reduce_only": True}, "live_llm_position"),
        _FakeOrder({"exit_authority": "ACTIVE_BASE_EXIT", "reduce_only": True}),
        _FakeOrder({}, "manual_api"),
    ]
    pending = mode.pending_new_risk_orders(orders)
    assert len(pending) == 2
    assert all(
        mode.order_class(order.metadata, order.strategy_id) == "NEW_RISK" for order in pending
    )


def test_five_minute_probe_windows() -> None:
    mode = OfflineMode()
    mode.enter("TEST", now=BASE)
    assert mode.probe_due(now=BASE + timedelta(seconds=299)) is False
    assert mode.probe_due(now=BASE + timedelta(seconds=300)) is True
    mode.probe_failed(now=BASE + timedelta(seconds=300))
    assert mode.windows == 2
    assert mode.next_probe_at == BASE + timedelta(seconds=600)
    assert mode.probe_due(now=BASE + timedelta(seconds=599)) is False
    assert mode.probe_due(now=BASE + timedelta(seconds=600)) is True


def test_recovery_requires_factual_reconciliation() -> None:
    mode = OfflineMode()
    mode.enter("TEST", now=BASE)
    mode.begin_recovery(now=BASE + timedelta(seconds=300))
    assert mode.complete_recovery(reconciled=False, now=BASE + timedelta(seconds=300)) is False
    assert mode.is_offline is True
    assert mode.windows == 2  # mismatch schedules the next window

    mode.begin_recovery(now=BASE + timedelta(seconds=600))
    assert mode.complete_recovery(reconciled=True, now=BASE + timedelta(seconds=600)) is True
    assert mode.is_offline is False
    assert mode.allows_new_risk() is True
    assert any(event["event"] == "OFFLINE_RECOVERED" for event in mode.events)


async def _open_position(engine, database, *, base_trigger: str = ">=1") -> None:
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="offline-entry",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="offline mode test",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=90,
        plan_contract_version=2,
        capital_allocation_pct=20.0,
        strategy="BREAKOUT",
        base_exit=BaseExitPlan(
            type="PRICE", trigger=base_trigger, size_pct=100, reason_code="BASE_EXIT"
        ),
        based_on_state_version="entry_v1",
        expected_edge_bps=50.0,
        expected_cost_bps=10.0,
        model_provider="deepseek",
        model="deepseek-chat",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="offline-test")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101")
    )
    assert plan is not None and signal is not None
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is not None and position.quantity > 0


async def test_engine_blocks_new_risk_and_still_protects_when_offline(database) -> None:
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-offline")
    assert await engine._strategy_context("BTCUSDT") is not None
    await _open_position(engine, database)

    assert await engine.enter_offline_mode("ALL_PROVIDERS_FAILED") is True
    mode = engine.offline_mode.snapshot()
    assert mode["offline"] is True and mode["windows"] == 1

    # New risk is blocked by the canonical process_signal guard.
    decisions = LLMDecisionStore(database.session_factory)
    blocked_entry = ChiefTraderDecision(
        decision_id="offline-blocked-entry",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="must be blocked while offline",
        position_size_request=0.1,
        leverage_request=2,
        stop_loss=90,
        plan_contract_version=2,
        capital_allocation_pct=20.0,
        strategy="BREAKOUT",
        base_exit=BaseExitPlan(type="PRICE", trigger=">=1", size_pct=100),
        based_on_state_version="offline_v1",
        expected_edge_bps=50.0,
        expected_cost_bps=10.0,
        model_provider="deepseek",
        model="deepseek-chat",
    )
    await decisions.save(blocked_entry, run_id=engine.run_id, prompt_version="offline-test")
    _, blocked_signal = await LiveLLMTradePlanner(
        TradePlanService(database.session_factory)
    ).create_entry_signal(blocked_entry, limit_price=Decimal("101"))
    assert blocked_signal is not None
    blocked_decision = await engine.process_signal(blocked_signal)
    assert blocked_decision is None

    # A protective Active Base Exit still fires while offline.
    await engine.tick()
    await engine.wait_for_event_queue()
    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is None or position.quantity == 0
    orders = await engine.order_manager.list_all(limit=50)
    assert any(order.metadata.get("exit_authority") == "ACTIVE_BASE_EXIT" for order in orders)

    async with database.session_factory() as session:
        actions = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    assert "LLM_OFFLINE_MODE" in actions
    await engine.stop()


async def test_engine_syncs_offline_state_from_router(database) -> None:
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.llm_router = _FakeRouter(offline=True)
    await engine.start("run-offline-sync")
    await engine.tick()
    assert engine.offline_mode.is_offline is True

    engine.llm_router.offline = False
    await engine.tick()
    assert engine.offline_mode.is_offline is False
    assert engine.health.snapshot()["components"]["llm_offline_mode"]["ok"] is False
    await engine.stop()


async def test_runtime_snapshot_exposes_router_diagnostics_and_offline_state(database) -> None:
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.llm_router = _FakeRouter(offline=True)
    await engine.start("run-offline-observability")
    await engine.tick()

    snapshot = engine.runtime_snapshot()
    assert snapshot["llm_router"]["router"] == "fake"
    assert snapshot["llm_offline_mode"]["offline"] is True
    assert snapshot["llm_offline_mode"]["windows"] == 1

    engine.llm_router = None
    assert engine.runtime_snapshot()["llm_router"] is None
    await engine.stop()
