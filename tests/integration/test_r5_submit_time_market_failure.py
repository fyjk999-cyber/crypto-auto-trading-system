"""R5 (unified candidate): submit-time MARKET_DATA_UNAVAILABLE -> REJECTED, never UNKNOWN.

Ported BY BEHAVIOUR from the reliability branch and re-run HERE, because an R5
pass on a different branch is not evidence for this candidate. Behaviour is
unchanged; the only adaptation is the Sizing V2 explicit entry quantity this
branch requires.

Reproduces the original incident on the production path:

    factual OPEN position + ACTIVE TradePlan
      -> canonical PositionReview REDUCE (deterministic chief through the real
         LiveLLMPositionManager, so decision lineage is genuine)
      -> RiskEngine + ExecutionAuthority
      -> durable order created
      -> PaperRealMarketAdapter.submit_order()
      -> the adapter's own market refresh fails
      -> MarketDataUnhealthy -> OrderRejected("MARKET_DATA_UNAVAILABLE")
      -> durable REJECTED

Nothing raises OrderRejected directly - the adapter performs the conversion,
which is exactly what the incident got wrong: OrderRejected subclasses
ExchangeError, so a clause ordered ExchangeError-first made the OrderRejected
branch dead code and recorded the refusal as UNKNOWN, permanently blocking the
plan's REDUCE/EXIT path.

The fixture's first blocker was measured, not guessed: with only a public market
feed the engine's instrument registry was EMPTY, ExecutionAuthority rejected with
SYMBOL_NOT_TRADEABLE and no order was ever created. The fake feed therefore has to
serve BOTH facts - market state AND exchange instrument metadata.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.market_data.state import DataHealth, MarketState
from crypto_trader.persistence.models import (
    FillORM,
    OrderEventORM,
    OrderORM,
    PositionProjectionORM,
    TradePlanORM,
)
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter
from crypto_trader.trade_plan.service import TradePlanService
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import (
    BTC_EXECUTION_METADATA,
    Evidence,
)

SYMBOL = "BTCUSDT"


class _InstrumentClient:
    """Serves the exchange instrument registry the adapter loads from."""

    async def get_instruments(self, instrument_type: str) -> list[dict]:
        return [
            {
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "ctType": "linear",
                "state": "live",
                "tickSz": "0.1",
                "lotSz": "0.01",
                "minSz": "0.01",
                "ctVal": "1",
                "ctMult": "1",
                "ctValCcy": "BTC",
                "settleCcy": "USDT",
                "listTime": "1600000000000",
                "expTime": "",
            }
        ]


class _ControllableFeed:
    """Healthy public feed + instrument registry, failing only on demand."""

    def __init__(self) -> None:
        self.fail_next_refresh = False
        self.client = _InstrumentClient()

    async def close(self) -> None:
        return None

    async def refresh(self, symbol: str) -> MarketState:
        healthy = not self.fail_next_refresh
        return MarketState(
            symbol=symbol,
            best_bid=Decimal("100.0") if healthy else Decimal("0"),
            best_ask=Decimal("100.5") if healthy else Decimal("0"),
            best_bid_size=Decimal("10") if healthy else Decimal("0"),
            best_ask_size=Decimal("10") if healthy else Decimal("0"),
            health=DataHealth.HEALTHY if healthy else DataHealth.UNAVAILABLE,
        )


class _ReduceChief:
    """TEST FIXTURE DECISION - not a production decision."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, ctx):
        self.calls += 1
        return ChiefTraderDecision(
            decision_id=f"r5-reduce-{self.calls}",
            symbol=ctx.symbol,
            position_state=getattr(ctx, "position_state", None) or "OPEN",
            action="REDUCE",
            market_regime=ctx.regime,
            thesis="R5 TEST FIXTURE DECISION",
            position_size_request=0.04,
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )


async def _await_position(engine, symbol, *, predicate, deadline_seconds=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    while True:
        position = await engine.portfolio.get_position(symbol)
        if position is not None and predicate(Decimal(str(position.quantity))):
            return position
        if loop.time() >= deadline:
            raise AssertionError(
                f"position {symbol} did not reach the expected quantity "
                f"(actual={None if position is None else position.quantity})"
            )
        await engine.wait_for_event_queue()
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_R5_submit_time_market_failure_is_REJECTED_not_UNKNOWN(database):
    feed = _ControllableFeed()
    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("100000")}, feed=feed
    )
    engine = make_paper_engine(
        database,
        simulator=adapter,
        database_url=database.url,
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=1,
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
    )
    await engine.start("run-r5")
    try:
        # §8 instrument precondition - proven through the ADAPTER, not by injecting.
        assert SYMBOL in engine._instruments, "instrument registry was not loaded"
        instrument = engine._instruments[SYMBOL]
        assert instrument.instrument_type == "LINEAR_PERP"
        assert Decimal(str(instrument.contract_size)) > 0
        assert Decimal(str(instrument.contract_multiplier)) > 0

        await adapter.refresh_market_state(SYMBOL)

        # ---------------------------------------------------------- factual entry
        decisions = LLMDecisionStore(database.session_factory)
        plans = TradePlanService(database.session_factory)
        entry = ChiefTraderDecision(
            decision_id="r5-entry",
            symbol=SYMBOL,
            action="LONG",
            market_regime="TREND",
            thesis="r5 entry",
            position_size_request=0.1,
            leverage_request=10,
            stop_loss=95,
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )
        await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
        plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
            entry,
            # Sizing V2: the authoritative quantity must be supplied explicitly;
            # the advisory position_size_request is never an order quantity.
            quantity=Decimal("0.1"),
            limit_price=Decimal("100.5"),
            execution_metadata=BTC_EXECUTION_METADATA,
        )
        await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
        await engine.process_signal(signal)
        position = await _await_position(
            engine, SYMBOL, predicate=lambda q: q != 0
        )
        qty_before = Decimal(str(position.quantity))
        assert qty_before != 0

        async with database.session_factory() as session:
            entry_orders = (
                await session.execute(
                    select(OrderORM).where(OrderORM.strategy_id == "live_llm")
                )
            ).scalars().all()
            plan_row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
        assert len(list(entry_orders)) >= 1, "the entry produced no durable order"
        assert plan_row.state == "ACTIVE", "the entry plan did not become ACTIVE"

        # ------------------------------------------------ canonical PositionReview
        engine.position_manager = LiveLLMPositionManager(
            chief=_ReduceChief(),
            evidence_engine=Evidence(),
            decisions=decisions,
            plans=plans,
            audit=engine.audit,
            review_cooldown_seconds=0,
        )

        # ------------------------------- fail ONLY once submit_order is reached
        #
        # Patched on the INSTANCE only. Patching the class would leak into every
        # other test that uses PaperRealMarketAdapter - an earlier version did
        # exactly that and broke two unrelated simulator tests.
        counters = {"adapter_submit": 0, "broker_submit": 0}
        original_submit = adapter.submit_order
        base_submit = SimulatedExchangeAdapter.submit_order

        async def counting_base(order):
            counters["broker_submit"] += 1
            return await base_submit(adapter, order)

        adapter.submit_order = counting_base

        async def fail_at_submit(order):
            counters["adapter_submit"] += 1
            adapter.books.pop(order.symbol, None)
            feed.fail_next_refresh = True
            return await original_submit(order)

        adapter.submit_order = fail_at_submit
        try:
            await engine.tick()
        finally:
            adapter.submit_order = original_submit

        assert counters["adapter_submit"] == 1, (
            f"the adapter's submit path was not reached "
            f"(calls={counters['adapter_submit']})"
        )
        assert counters["broker_submit"] == 0, (
            "the failure must occur BEFORE the broker is reached"
        )

        # ------------------------------------------------------ durable outcome
        async with database.session_factory() as session:
            action_orders = (
                await session.execute(
                    select(OrderORM)
                    .where(OrderORM.strategy_id == "live_llm_position")
                    .order_by(OrderORM.created_at.desc())
                )
            ).scalars().all()
            plan_row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
                )
            ).scalar_one()
            position_after = (
                await session.execute(
                    select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
                )
            ).scalar_one()
        assert action_orders, "the REDUCE produced no durable order"
        row = action_orders[0]
        assert row.status == "REJECTED", (
            f"expected REJECTED, got {row.status} - a submit-time pre-broker refusal "
            "must never be recorded as UNKNOWN"
        )
        assert "MARKET_DATA_UNAVAILABLE" in (row.rejection_reason or "")
        assert row.exchange_order_id is None
        assert Decimal(str(row.filled_quantity)) == Decimal("0")

        async with database.session_factory() as session:
            fill_count = (
                await session.execute(
                    select(func.count())
                    .select_from(FillORM)
                    .where(FillORM.order_id == row.internal_order_id)
                )
            ).scalar_one()
            unknown_count = (
                await session.execute(
                    select(func.count())
                    .select_from(OrderORM)
                    .where(OrderORM.status == "UNKNOWN")
                )
            ).scalar_one()
            events = (
                await session.execute(
                    select(OrderEventORM.event_type).where(
                        OrderEventORM.order_id == row.internal_order_id
                    )
                )
            ).scalars().all()
        assert fill_count == 0, "a pre-broker refusal must not create a fill"
        assert unknown_count == 0, "an UNKNOWN order was created"
        assert not any("UNKNOWN" in str(e) for e in events), (
            f"an UNKNOWN event was recorded: {sorted(set(map(str, events)))}"
        )

        # ------------------------------------------- preservation + deadlock check
        assert Decimal(str(position_after.quantity)) == qty_before, (
            "a refused reduction changed the factual position"
        )
        assert plan_row.state == "ACTIVE", (
            f"the plan must survive a refused reduction, got {plan_row.state}"
        )
        pending = await engine.order_manager.has_pending_position_action(plan.trade_plan_id)
        assert pending is False, (
            "a submit-time refusal still blocks position management - the exact "
            "deadlock the incident produced"
        )
    finally:
        await engine.stop()
