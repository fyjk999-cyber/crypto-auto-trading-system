from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import Account, Position
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.observability.audit import AuditService
from crypto_trader.strategy.base import StrategyContext
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState


class Evidence:
    def analyze_evidence(self, _ctx):
        return {
            "regime": {"regime": "TREND"},
            "source_refs": ["okx:ETH-USDT-SWAP", "tool:trend"],
        }


class Chief:
    def __init__(self, action: str, quantity: str = "0") -> None:
        self.action = action
        self.quantity = quantity
        self.calls = 0
        self.last_context = None

    async def decide(self, ctx):
        self.calls += 1
        self.last_context = ctx
        return ChiefTraderDecision(
            decision_id=f"open-{self.action.lower()}",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action=self.action,
            market_regime=ctx.regime,
            thesis=f"canonical {self.action.lower()}",
            position_size_request=float(self.quantity),
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )


async def active_plan(database, direction: str):
    plans = TradePlanService(database.session_factory)
    plan = await plans.create(
        decision_id=f"entry-{direction.lower()}",
        symbol="ETHUSDT",
        direction=direction,
        thesis="original factual thesis",
        requested_quantity=Decimal("2"),
    )
    await plans.transition(plan.trade_plan_id, TradePlanState.APPROVED)
    return await plans.transition(plan.trade_plan_id, TradePlanState.ACTIVE)


def context(quantity: str) -> tuple[StrategyContext, Position]:
    now = datetime.now(UTC)
    book = OrderBook(symbol="ETHUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal("99"), Decimal("10"))],
        [(Decimal("101"), Decimal("10"))],
        now=now,
    )
    position = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal(quantity),
        avg_entry_price=Decimal("95"),
        cost_basis=Decimal("190"),
        updated_at=now,
    )
    return (
        StrategyContext(
            symbol="ETHUSDT",
            book=book,
            account=Account(equity=Decimal("1000")),
            positions={"ETHUSDT": position},
            clock_time=now,
            run_id="run-open",
            mark_price=Decimal("100"),
        ),
        position,
    )


def manager(database, chief: Chief) -> LiveLLMPositionManager:
    return LiveLLMPositionManager(
        chief=chief,
        evidence_engine=Evidence(),
        decisions=LLMDecisionStore(database.session_factory),
        plans=TradePlanService(database.session_factory),
        audit=AuditService(database.session_factory),
    )


async def test_hold_is_durable_and_keeps_tradeplan_active(database):
    plan = await active_plan(database, "LONG")
    ctx, position = context("2")
    signal = await manager(database, Chief("HOLD")).review(ctx, position)
    assert signal is None
    stored = await LLMDecisionStore(database.session_factory).get("open-hold")
    assert stored is not None and stored.action == "HOLD"
    current = await TradePlanService(database.session_factory).get(plan.trade_plan_id)
    assert current is not None and current.state == TradePlanState.ACTIVE
    assert current.latest_position_decision_id == "open-hold"


async def test_reduce_and_exit_are_reduce_only_and_side_symmetric(database):
    await active_plan(database, "LONG")
    long_ctx, long_position = context("2")
    reduce_signal = await manager(database, Chief("REDUCE", "0.5")).review(
        long_ctx, long_position
    )
    assert reduce_signal is not None
    assert reduce_signal.side == OrderSide.SELL
    assert reduce_signal.quantity == Decimal("0.5")
    assert reduce_signal.metadata["reduce_only"] is True

    database2 = database
    plans = TradePlanService(database2.session_factory)
    current = await plans.get_active_for_symbol("ETHUSDT")
    assert current is not None
    await plans.transition(current.trade_plan_id, TradePlanState.CLOSED, reason="test-boundary")
    await active_plan(database2, "SHORT")
    short_ctx, short_position = context("-2")
    exit_signal = await manager(database2, Chief("EXIT")).review(short_ctx, short_position)
    assert exit_signal is not None
    assert exit_signal.side == OrderSide.BUY
    assert exit_signal.quantity == Decimal("2")
    assert exit_signal.metadata["lifecycle_action"] == "EXIT"
    assert exit_signal.metadata["reduce_only"] is True


async def test_reduce_cannot_cross_zero_and_cooldown_applies_to_hold(database):
    await active_plan(database, "LONG")
    ctx, position = context("2")
    invalid = await manager(database, Chief("REDUCE", "3")).review(ctx, position)
    assert invalid is None

    chief = Chief("HOLD")
    subject = manager(database, chief)
    await subject.review(ctx, position)
    await subject.review(ctx, position)
    assert chief.calls == 1


async def test_open_context_uses_factual_market_and_contract_aware_pnl(database):
    await active_plan(database, "LONG")
    ctx, position = context("2")
    position.contract_size = Decimal("0.01")
    position.contract_multiplier = Decimal("2")
    ctx.index_price = Decimal("100.5")
    ctx.funding = Decimal("0.0001")
    ctx.oi = Decimal("12345")
    ctx.basis = Decimal("-0.5")
    chief = Chief("HOLD")

    assert await manager(database, chief).review(ctx, position) is None

    captured = chief.last_context
    assert captured is not None
    assert captured.market_snapshot == {
        "symbol": "ETHUSDT",
        "timestamp": ctx.clock_time.isoformat(),
        "best_bid": "99",
        "best_ask": "101",
        "mark_price": "100",
        "index_price": "100.5",
        "funding": "0.0001",
        "open_interest": "12345",
        "basis": "-0.5",
        "source": "OKX_PUBLIC",
        "instrument": None,
    }
    assert captured.position_context["unrealized_pnl"] == "0.20"
