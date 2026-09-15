"""Phase 4 L1 wake test: Risk L1 bypasses the ordinary position-review cooldown.

The engine marks a deterministic wake intent (requires_llm_reassessment=True)
and passes force=True to the canonical position manager, so a Risk L1 warning
is reassessed immediately instead of waiting for the fixed review cadence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.models import Account, Position
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
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
    async def log(self, *args, **kwargs):
        return None


class _Chief:
    def __init__(self):
        self.calls = 0

    async def decide(self, ctx):
        self.calls += 1
        return ChiefTraderDecision(
            decision_id=f"pos-{self.calls}",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action="HOLD",
            market_regime=ctx.regime,
            thesis="hold",
            model_provider="deepseek",
            model="deepseek-chat",
        )


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
