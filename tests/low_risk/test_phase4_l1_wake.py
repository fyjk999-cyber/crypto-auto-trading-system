"""Phase 4 L1 wake test: Risk L1 bypasses the ordinary position-review cooldown.

The engine marks a deterministic wake intent (requires_llm_reassessment=True)
and passes force=True to the canonical position manager, so a Risk L1 warning
is reassessed immediately instead of waiting for the fixed review cadence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent

from crypto_trader.domain.models import Account, Position
from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.strategy.base import StrategyContext

NOW = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)


class _Plan:
    trade_plan_id = "plan-1"
    decision_id = "entry-1"
    thesis = "thesis"
    invalidation_conditions: list[str] = []
    reduce_conditions: list[str] = []
    exit_conditions: list[str] = []
    expected_holding_period = "4h"
    max_holding_time_seconds = 86400.0
    opened_at = NOW
    direction = "LONG"
    requested_leverage = Decimal("2")


class _Plans:
    async def get_active_for_symbol(self, symbol):
        return _Plan()

    async def link_position_decision(self, plan_id, decision_id):
        return None


class _Evidence:
    def analyze_evidence(self, ctx):
        return {"regime": {"regime": "TREND_UP"}, "source_refs": []}


class _Decisions:
    def __init__(self):
        self.saved = 0

    async def save(self, decision, **kwargs):
        self.saved += 1

    async def link_trade_plan(self, decision_id, plan_id):
        return None


class _Audit:
    def __init__(self):
        self.events = []

    async def log(self, action, *args, **kwargs):
        self.events.append(action)


class _Chief:
    def __init__(self, action="HOLD", extra=None):
        self.calls = 0
        self.last_rebuild = None
        self.action = action
        self.extra = extra or {}

    def render_prompt(self, ctx):
        return f"PROMPT {ctx.symbol}"

    async def decide(self, ctx, *, rebuild_context=None):
        self.calls += 1
        self.last_rebuild = rebuild_context
        values = dict(
            decision_id=f"pos-{self.calls}",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action=self.action,
            market_regime=ctx.regime,
            thesis="reassess",
            position_size_request=0.5,
            leverage_request=2,
            model_provider="deepseek",
            model="deepseek-chat",
        )
        values.update(self.extra)
        return ChiefTraderDecision(**values)


def _ctx() -> StrategyContext:
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    book.apply_snapshot(1, [(Decimal("99.9"), Decimal("1"))], [(Decimal("100.1"), Decimal("1"))])
    position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        updated_at=NOW,
    )
    return StrategyContext(
        symbol="BTCUSDT",
        book=book,
        account=Account(equity=Decimal("10000"), updated_at=NOW),
        positions={"BTCUSDT": position},
        clock_time=NOW,
        run_id="run-l1",
    )


async def test_risk_l1_force_bypasses_review_cooldown() -> None:
    chief = _Chief()
    decisions = _Decisions()
    manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=_Evidence(),
        decisions=decisions,
        plans=_Plans(),
        audit=_Audit(),
        review_cooldown_seconds=30.0,
        attempt_clock=lambda: NOW,
    )
    ctx = _ctx()
    position = ctx.positions["BTCUSDT"]

    assert await manager.review(ctx, position) is None
    assert chief.calls == 1

    # Ordinary cadence: the cooldown suppresses a repeat review.
    assert await manager.review(ctx, position) is None
    assert chief.calls == 1

    # Risk L1 material wake: force=True must reassess immediately.
    assert await manager.review(ctx, position, force=True) is None
    assert chief.calls == 2
    assert decisions.saved == 2


async def test_position_review_passes_fresh_context_rebuilder() -> None:
    chief = _Chief()
    decisions = _Decisions()

    async def fresh_provider(symbol, ctx):
        fresh = _ctx()
        fresh.state_version = "v42"
        return fresh

    manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=_Evidence(),
        decisions=decisions,
        plans=_Plans(),
        audit=_Audit(),
        review_cooldown_seconds=30.0,
        attempt_clock=lambda: NOW,
        fresh_context_provider=fresh_provider,
    )
    ctx = _ctx()
    await manager.review(ctx, ctx.positions["BTCUSDT"])

    assert chief.last_rebuild is not None
    prompt, version = await chief.last_rebuild()
    assert version == "v42"
    assert "BTCUSDT" in prompt


async def test_fresh_provider_returning_none_fails_safe() -> None:
    chief = _Chief()

    async def fresh_provider(symbol, ctx):
        return None

    manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=_Evidence(),
        decisions=_Decisions(),
        plans=_Plans(),
        audit=_Audit(),
        review_cooldown_seconds=30.0,
        attempt_clock=lambda: NOW,
        fresh_context_provider=fresh_provider,
    )
    ctx = _ctx()
    await manager.review(ctx, ctx.positions["BTCUSDT"])
    import pytest

    with pytest.raises(RuntimeError, match="NO_FRESH_CONTEXT"):
        await chief.last_rebuild()


async def test_hedge_and_reverse_never_become_reduce_only_orders() -> None:
    for action in ("HEDGE", "REVERSE"):
        chief = _Chief(action=action)
        audit = _Audit()
        manager = LiveLLMPositionManager(
            chief=chief,
            evidence_engine=_Evidence(),
            decisions=_Decisions(),
            plans=_Plans(),
            audit=audit,
            review_cooldown_seconds=30.0,
            attempt_clock=lambda: NOW,
        )
        ctx = _ctx()
        signal = await manager.review(ctx, ctx.positions["BTCUSDT"])
        assert signal is None, f"{action} must not produce a reduce-only signal"
        assert "HEDGE_REVERSE_REQUIRES_CORE_NEW_RISK" in audit.events


class _HedgePlanner:
    def __init__(self):
        self.calls = 0
        self.contract = None

    async def create_hedge_signal(
        self,
        decision,
        *,
        hedge_contract,
        existing_legs,
        current_position_side,
        limit_price=None,
        quantity=None,
    ):
        self.calls += 1
        self.contract = hedge_contract
        return (
            SimpleNamespace(trade_plan_id="hedge-plan-1"),
            SignalIntent(
                signal_id="hedge-signal-1",
                strategy_id="live_llm",
                symbol=decision.symbol,
                side=OrderSide.SELL,
                quantity=Decimal("0.5"),
                reason=decision.thesis,
                metadata={
                    "lifecycle_action": "HEDGE",
                    "leg_id": hedge_contract.leg_id,
                    "reduce_only": False,
                },
            ),
        )


_HEDGE_EXTRA = dict(
    plan_contract_version=2,
    capital_allocation_pct=10.0,
    strategy="MEAN_REVERT",
    thesis="independent mean-reversion short thesis",
    base_exit=BaseExitPlan(type="PRICE", trigger="<=104", size_pct=100),
    thesis_invalidation="acceptance above 105",
    supporting_evidence=["model:mean_reversion"],
    based_on_state_version="v1",
    expected_edge_bps=40.0,
    expected_cost_bps=8.0,
)


async def test_valid_hedge_uses_new_risk_planner_and_registers_leg() -> None:
    chief = _Chief(action="HEDGE", extra=_HEDGE_EXTRA)
    audit = _Audit()
    planner = _HedgePlanner()
    manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=_Evidence(),
        decisions=_Decisions(),
        plans=_Plans(),
        audit=audit,
        review_cooldown_seconds=30.0,
        attempt_clock=lambda: NOW,
        hedge_planner=planner,
    )
    ctx = _ctx()
    signal = await manager.review(ctx, ctx.positions["BTCUSDT"])
    assert signal is not None
    assert signal.metadata["lifecycle_action"] == "HEDGE"
    assert signal.metadata["reduce_only"] is False
    assert planner.calls == 1
    assert planner.contract is not None
    assert planner.contract.side == "SHORT"  # opposite of the LONG position
    assert "HEDGE_LEG_REGISTERED" in audit.events


async def test_illegal_hedge_reason_never_reaches_the_planner() -> None:
    chief = _Chief(
        action="HEDGE",
        extra={**_HEDGE_EXTRA, "thesis": "reduce loss on the original LONG"},
    )
    audit = _Audit()
    planner = _HedgePlanner()
    manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=_Evidence(),
        decisions=_Decisions(),
        plans=_Plans(),
        audit=audit,
        review_cooldown_seconds=30.0,
        attempt_clock=lambda: NOW,
        hedge_planner=planner,
    )
    ctx = _ctx()
    signal = await manager.review(ctx, ctx.positions["BTCUSDT"])
    assert signal is None
    assert planner.calls == 0
    assert "HEDGE_LEG_REJECTED" in audit.events
    assert "HEDGE_REVERSE_REQUIRES_CORE_NEW_RISK" in audit.events
