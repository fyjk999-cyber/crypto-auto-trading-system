"""Position-lifecycle determinism regression suite (L1-L12).

These tests exist because the lifecycle suite was intermittently flaky. The
root cause was NOT an arbitrary timeout: the exchange adapter emits
ack/open/fill events INLINE while ``submit_order`` is still in flight, and the
engine's event consumer resolved those events only by ``exchange_order_id`` —
which is persisted AFTER ``submit_order`` returns. An event consumed inside
that window found no local order and was **dropped permanently**, because the
apparent catch-up ``_apply_exchange_order_fill`` was dead code with no caller.

The flake was therefore a REAL runtime race, and every test below pins its
determinism without sleeps, retries or relaxed assertions:

L1  lifecycle transition is deterministic without arbitrary sleep
L2  TIME_STOP always outranks ADD
L3  ADD remains explicitly refused
L4  a pending ADD cannot fall through into REDUCE
L5  HOLD does not create an order
L6  REDUCE creates only reduce-only semantics
L7  EXIT precedence is deterministic
L8  a pending position action blocks a conflicting action
L9  a lifecycle run leaves zero background tasks
L10 a repeated lifecycle run produces an identical final state
L11 test ordering does not change the result
L12 the clock boundary exactly at TIME_STOP is deterministic
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.enums import ExchangeEventType, OrderSide, OrderStatus
from crypto_trader.domain.models import ExchangeEvent, OrderIntent
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.observability.audit import AuditService
from crypto_trader.persistence.database import Database
from crypto_trader.persistence.models import TradePlanORM
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import (
    BTC_EXECUTION_METADATA,
    Evidence,
    MutableClock,
    SequencedChief,
    _seed_known_zero_funding_coverage,
)


class InlineEventDrainedAdapter(SimulatedExchangeAdapter):
    """Deterministically selects the interleaving the venue can produce.

    The simulator emits ack/open/fill inline during ``submit_order``. Draining
    the engine's event queue *inside* ``submit_order`` guarantees those events
    are processed before the engine persists ``exchange_order_id`` — the exact
    production window in which the venue's event stream can beat the REST
    response and the local commit. No sleeps and no timeouts are involved.
    """

    def __init__(self, *args, event_gate=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.event_gate = event_gate

    async def submit_order(self, order):
        result = await super().submit_order(order)
        if self.event_gate is not None:
            await asyncio.wait_for(self.event_gate.join(), timeout=10)
        return result


class AddChief:
    """Asks to ADD to an open position."""

    def __init__(self, step: str = "ADD", quantity: str = "5") -> None:
        self.step = step
        self.quantity = quantity
        self.calls = 0

    async def decide(self, ctx):
        self.calls += 1
        return ChiefTraderDecision(
            decision_id=f"add-chief-{self.calls}",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action=self.step,
            market_regime=ctx.regime,
            thesis="trend continuation",
            position_size_request=float(self.quantity),
            stop_loss=98.0,
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )


async def _fresh_database(tmp_path, name: str):
    """A dedicated database per scenario, so a test cannot pass by accident."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/{name}.db")
    await db.init_schema()
    return db


async def _open_long_position(
    database,
    *,
    race: bool = True,
    run_id: str = "run-determinism",
    quantity: str = "0.1",
    ask_quantity: str = "1",
    decision_id: str = "det-entry",
    symbol: str = "BTCUSDT",
    max_holding_time_seconds: float = 86400.0,
):
    """Open one LONG position and return the whole deterministic fixture."""
    adapter = InlineEventDrainedAdapter(initial_balances={"USDT": Decimal("10000")})
    engine = make_paper_engine(database, engine_tick_seconds=3600, simulator=adapter)
    if race:
        adapter.event_gate = engine._event_queue
    clock = MutableClock()
    engine.clock = clock
    await engine.start(run_id)
    assert await engine._strategy_context(symbol) is not None
    if ask_quantity != "1":
        book = adapter.books[symbol]
        book.apply_snapshot(
            adapter.sequence["BTCUSDT"] + 1,
            [(Decimal("99.95"), Decimal("1"))],
            [(Decimal("100.05"), Decimal(ask_quantity))],
        )

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id=decision_id,
        symbol=symbol,
        action="LONG",
        market_regime="TREND",
        thesis="deterministic lifecycle entry",
        position_size_request=float(quantity),
        leverage_request=2,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="det-v1")
    plan, signal = await LiveLLMTradePlanner(
        plans, max_holding_time_seconds=max_holding_time_seconds
    ).create_entry_signal(
        entry,
        quantity=Decimal(quantity),
        limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    # The OPENED plan carries the factual opened_at, which the funding-coverage
    # window and the holding clock are both derived from.
    opened = await plans.get(plan.trade_plan_id)
    assert opened is not None
    return engine, adapter, clock, decisions, plans, opened


async def _age_plan(engine, database, plan, seconds: float) -> None:
    """Set the plan's factual opened_at so the holding clock is exact."""
    async with database.session_factory() as session:
        row = await session.get(TradePlanORM, plan.trade_plan_id)
        assert row is not None
        row.opened_at = engine.clock.now() - timedelta(seconds=seconds)
        await session.commit()


def _install_manager(engine, decisions, plans, sequence, *, cooldown=30):
    chief = SequencedChief(sequence)
    engine.position_manager = LiveLLMPositionManager(
        chief=chief,
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=cooldown,
    )
    return chief


async def _final_state(engine, plans, plan, symbol: str = "BTCUSDT"):
    position = await engine.portfolio.get_position(symbol)
    current = await plans.get(plan.trade_plan_id)
    # Client order ids embed per-decision identities, so they are deliberately
    # excluded: the comparable state is the OBSERVABLE lifecycle outcome.
    orders = sorted(
        (order.status.value, str(order.quantity), str(order.filled_quantity))
        for order in engine.adapter.orders.values()
    )
    return {
        "position_quantity": str(position.quantity) if position else None,
        "plan_state": current.state.value if current else None,
        "orders": orders,
    }


# ==================================================================== L1
async def test_L1_lifecycle_transition_is_deterministic_without_any_sleep(database):
    """The venue's inline fill must still project, with no sleep anywhere.

    This is the root-cause regression: every inline event is guaranteed to be
    processed BEFORE the engine persists the exchange order id.
    """
    engine, adapter, _, _, plans, plan = await _open_long_position(database)
    try:
        venue_order = next(iter(adapter.orders.values()))
        assert venue_order.status == OrderStatus.FILLED
        assert venue_order.filled_quantity == Decimal("0.1")

        current = await plans.get(plan.trade_plan_id)
        position = await engine.portfolio.get_position("BTCUSDT")
        assert current is not None and current.state == TradePlanState.ACTIVE
        assert position is not None and position.quantity == Decimal("0.1")
        # No event was merely "tolerated": a settled entry has no anomaly at all.
        anomalies = [
            row
            for row in await AuditService(database.session_factory).list_recent(limit=60)
            if row.action
            in {"EXCHANGE_EVENT_UNMATCHED", "EXCHANGE_EVENT_ID_MISMATCH",
                "EXCHANGE_EVENT_FAILED"}
        ]
        assert anomalies == []
    finally:
        await engine.stop()


async def test_L1b_a_lost_fill_is_never_silent(database):
    """If an event genuinely cannot be matched, it must be auditable."""
    engine, adapter, _, _, plans, plan = await _open_long_position(database, race=False)
    try:
        # An event for an order that does not exist locally at all.
        await engine.process_exchange_event(
            ExchangeEvent(
                event_id="evt-unmatched",
                event_type=ExchangeEventType.ORDER_ACK,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": "sim_does_not_exist",
                    "client_order_id": "no_such_client_order",
                    "symbol": "BTCUSDT",
                },
            )
        )
        events = [
            row
            for row in await AuditService(database.session_factory).list_recent(limit=50)
            if row.action == "EXCHANGE_EVENT_UNMATCHED"
        ]
        assert len(events) == 1
        assert events[0].after_json["reason"] == "NO_LOCAL_ORDER_FOR_EVENT"
    finally:
        await engine.stop()


# ==================================================================== L2 / L3
async def test_L2_time_stop_outranks_add(database):
    """At the factual max-hold boundary an ADD cannot win: REDUCE takes over."""
    engine, adapter, _, decisions, plans, plan = await _open_long_position(
        database, max_holding_time_seconds=3600.0
    )
    try:
        await _seed_known_zero_funding_coverage(database, plan)
        await _age_plan(engine, database, plan, 3600.0)
        _install_manager(engine, decisions, plans, [])  # chief never consulted
        engine.position_manager.chief = AddChief("ADD")

        before = len(adapter.orders)
        await engine.tick()
        await engine.wait_for_event_queue()

        created = list(adapter.orders.values())[before:]
        assert len(created) == 1
        order = created[0]
        # The safety boundary produced a full reduce-only close, not an ADD.
        assert order.metadata.get("reduce_only") is True
        assert order.side == OrderSide.SELL
        assert order.quantity == Decimal("0.1")
        audit = AuditService(database.session_factory)
        actions = [row.action for row in await audit.list_recent(limit=80)]
        assert "LIVE_LLM_POSITION_ADD_OVERRIDDEN_BY_TIME_STOP" in actions
        assert "LIVE_LLM_POSITION_ADD_REFUSED" not in actions
    finally:
        await engine.stop()


async def test_L3_add_remains_explicitly_refused(database):
    engine, adapter, _, decisions, plans, plan = await _open_long_position(database)
    try:
        await _seed_known_zero_funding_coverage(database, plan)
        _install_manager(engine, decisions, plans, [])
        engine.position_manager.chief = AddChief("ADD")

        before = len(adapter.orders)
        await engine.tick()
        await engine.wait_for_event_queue()

        assert len(adapter.orders) == before  # zero orders
        stored = await LLMDecisionStore(database.session_factory).get("add-chief-1")
        assert stored is not None and stored.action == "ADD"
        audit = AuditService(database.session_factory)
        refused = [
            row
            for row in await audit.list_recent(limit=80)
            if row.action == "LIVE_LLM_POSITION_ADD_REFUSED"
        ]
        assert len(refused) == 1
        assert refused[0].after_json["reason"] == "ADD_EXECUTION_DISABLED_FEATURE_FLAG"
        assert refused[0].after_json["reduce_substitution_blocked"] is True
    finally:
        await engine.stop()


# ==================================================================== L4
async def test_L4_pending_add_cannot_fall_through_into_reduce(database):
    """An ADD must never be executed as a REDUCE, and must not shrink the size."""
    engine, adapter, _, decisions, plans, plan = await _open_long_position(database)
    try:
        await _seed_known_zero_funding_coverage(database, plan)
        _install_manager(engine, decisions, plans, [])
        engine.position_manager.chief = AddChief("ADD")

        for _ in range(3):
            await engine.tick()
            await engine.wait_for_event_queue()

        position = await engine.portfolio.get_position("BTCUSDT")
        assert position is not None and position.quantity == Decimal("0.1")
        assert len(adapter.orders) == 1
    finally:
        await engine.stop()


# ==================================================================== L5
async def test_L5_hold_creates_no_order(database):
    engine, adapter, _, decisions, plans, plan = await _open_long_position(database)
    try:
        await _seed_known_zero_funding_coverage(database, plan)
        _install_manager(engine, decisions, plans, [("HOLD", "0")])

        before = len(adapter.orders)
        await engine.tick()
        await engine.wait_for_event_queue()

        assert len(adapter.orders) == before
        current = await plans.get(plan.trade_plan_id)
        assert current is not None and current.state == TradePlanState.ACTIVE
    finally:
        await engine.stop()


# ==================================================================== L6
async def test_L6_reduce_is_reduce_only_and_bounded(database):
    engine, adapter, _, decisions, plans, plan = await _open_long_position(database)
    try:
        await _seed_known_zero_funding_coverage(database, plan)
        _install_manager(engine, decisions, plans, [("REDUCE", "0.04")])

        before = len(adapter.orders)
        await engine.tick()
        await engine.wait_for_event_queue()

        created = list(adapter.orders.values())[before:]
        assert len(created) == 1
        assert created[0].metadata.get("reduce_only") is True
        assert created[0].side == OrderSide.SELL
        assert created[0].quantity == Decimal("0.04")
        # Never more than the factual position.
        assert created[0].quantity <= Decimal("0.1")
    finally:
        await engine.stop()


# ==================================================================== L7
async def test_L7_exit_precedence_is_deterministic(database, tmp_path):
    """EXIT is a full reduce-only close at every clock offset."""
    for advance in (0, 61, 3600):
        db = await _fresh_database(tmp_path, f"l7-{advance}")
        try:
            engine, adapter, clock, decisions, plans, plan = await _open_long_position(
                db, run_id=f"run-exit-{advance}", decision_id=f"exit-entry-{advance}"
            )
            try:
                await _seed_known_zero_funding_coverage(db, plan)
                if advance:
                    clock.advance(advance)
                _install_manager(engine, decisions, plans, [("EXIT", "0")])

                before = len(adapter.orders)
                await engine.tick()
                await engine.wait_for_event_queue()

                created = list(adapter.orders.values())[before:]
                assert len(created) == 1, f"advance={advance}"
                assert created[0].metadata.get("reduce_only") is True
                assert created[0].side == OrderSide.SELL
                assert created[0].quantity == Decimal("0.1")
                position = await engine.portfolio.get_position("BTCUSDT")
                assert position is not None and position.quantity == Decimal("0")
                current = await plans.get(plan.trade_plan_id)
                assert current is not None and current.state == TradePlanState.CLOSED
            finally:
                await engine.stop()
        finally:
            await db.close()


# ==================================================================== L8
async def test_L8_pending_position_action_blocks_a_conflicting_action(database):
    """A partially filled entry keeps its authority; nothing else may act."""
    engine, adapter, _, decisions, plans, plan = await _open_long_position(
        database, ask_quantity="0.04", decision_id="partial-entry"
    )
    try:
        venue_order = next(iter(adapter.orders.values()))
        assert venue_order.status == OrderStatus.PARTIALLY_FILLED
        position = await engine.portfolio.get_position("BTCUSDT")
        assert position is not None and position.quantity == Decimal("0.04")
        current = await plans.get(plan.trade_plan_id)
        assert current is not None and current.state == TradePlanState.ACTIVE

        _install_manager(engine, decisions, plans, [("EXIT", "0"), ("EXIT", "0")])
        before = len(adapter.orders)
        result = await engine.tick()
        await engine.wait_for_event_queue()

        assert result == []
        assert len(adapter.orders) == before
        after = await engine.portfolio.get_position("BTCUSDT")
        assert after is not None and after.quantity == Decimal("0.04")
    finally:
        await engine.stop()


# ==================================================================== L9
async def test_L9_lifecycle_run_leaves_zero_background_tasks(database):
    before_engine: set[str] = set()
    engine, adapter, _, _, _, _ = await _open_long_position(database)
    try:
        engine_tasks = {task.get_name() for task in engine._tasks}
        assert engine_tasks  # the runtime did start background work
        await engine.stop()
        before_engine = {
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }
        leaked = {name for name in before_engine if name.startswith("engine-")}
        assert leaked == set()
        assert not {name for name in before_engine if name in engine_tasks}
    finally:
        if engine._running:
            await engine.stop()


# ==================================================================== L10
async def test_L10_repeated_lifecycle_run_produces_an_identical_final_state(tmp_path):
    states = []
    for attempt in range(3):
        db = await _fresh_database(tmp_path, f"l10-{attempt}")
        try:
            engine, adapter, _, decisions, plans, plan = await _open_long_position(
                db, run_id=f"run-repeat-{attempt}", decision_id=f"repeat-entry-{attempt}"
            )
            try:
                await _seed_known_zero_funding_coverage(db, plan)
                _install_manager(engine, decisions, plans, [("REDUCE", "0.04")])
                await engine.tick()
                await engine.wait_for_event_queue()
                states.append(await _final_state(engine, plans, plan))
            finally:
                await engine.stop()
        finally:
            await db.close()

    assert states[0] == states[1] == states[2]
    assert states[0]["position_quantity"] == "0.06"
    assert states[0]["plan_state"] == TradePlanState.ACTIVE.value


async def test_L11_an_unrelated_lifecycle_does_not_change_this_one(database, tmp_path):
    """A previous open->close lifecycle must not perturb the next one.

    Both arms run the same scenario; the only difference is that the second arm
    runs it on a database that already carries a completed lifecycle. Any order
    dependence in lifecycle state, caches or background work would show up as a
    different final state.
    """

    async def scenario(db, *, run_id, decision_id):
        engine, adapter, _, decisions, plans, plan = await _open_long_position(
            db, run_id=run_id, decision_id=decision_id
        )
        try:
            await _seed_known_zero_funding_coverage(db, plan)
            _install_manager(engine, decisions, plans, [("REDUCE", "0.05")])
            await engine.tick()
            await engine.wait_for_event_queue()
            return await _final_state(engine, plans, plan)
        finally:
            await engine.stop()

    async def completed_lifecycle(db, *, run_id, decision_id):
        engine, adapter, _, decisions, plans, plan = await _open_long_position(
            db, run_id=run_id, decision_id=decision_id
        )
        try:
            await _seed_known_zero_funding_coverage(db, plan)
            _install_manager(engine, decisions, plans, [("EXIT", "0")])
            await engine.tick()
            await engine.wait_for_event_queue()
        finally:
            await engine.stop()

    alone_db = await _fresh_database(tmp_path, "l11-alone")
    try:
        alone = await scenario(alone_db, run_id="l11-alone", decision_id="l11-alone-entry")
    finally:
        await alone_db.close()

    # Unrelated lifecycle first, then the same scenario on the SAME database.
    await completed_lifecycle(database, run_id="l11-a", decision_id="l11-a-entry")
    after_prior = await scenario(
        database, run_id="l11-b", decision_id="l11-b-entry"
    )

    assert after_prior == alone


# ==================================================================== L12
async def test_L12_clock_boundary_exactly_at_time_stop_is_deterministic(tmp_path):
    """time_in_trade == max_holding is REACHED (>=); one second short is not."""
    for offset, expect_time_stop in ((0.0, True), (1.0, False)):
        db = await _fresh_database(tmp_path, f"l12-{offset}")
        try:
            engine, adapter, _, decisions, plans, plan = await _open_long_position(
                db,
                run_id=f"run-boundary-{offset}",
                decision_id=f"boundary-entry-{offset}",
                max_holding_time_seconds=3600.0,
            )
            try:
                await _seed_known_zero_funding_coverage(db, plan)
                await _age_plan(engine, db, plan, 3600.0 - offset)
                _install_manager(engine, decisions, plans, [("HOLD", "0")])

                before = len(adapter.orders)
                await engine.tick()
                await engine.wait_for_event_queue()
                created = list(adapter.orders.values())[before:]

                if expect_time_stop:
                    assert len(created) == 1, f"offset={offset}"
                    assert created[0].metadata["lifecycle_action"] == (
                        "TIME_STOP_SAFETY_FALLBACK"
                    )
                    assert created[0].metadata.get("reduce_only") is True
                else:
                    assert created == [], f"offset={offset}"
            finally:
                await engine.stop()
        finally:
            await db.close()


# ============================================ reviewer-driven hardening (R1/R2)
async def test_L13_an_event_bound_to_another_venue_order_is_refused(database):
    """R1/F-2: the client_order_id fallback must never RE-BIND venue identity.

    The crafted fill is sized to FIT the remaining quantity on purpose. A
    quantity larger than the remainder is refused by ``apply_fill``'s
    over-quantity backstop whatever the routing does, which would make the state
    assertions below pass on the vulnerable revision for the wrong reason. This
    payload is the one that actually exploited the fallback: it drove a real
    order's ``filled_quantity`` up, adopted the attacker's venue id (permanently
    orphaning the real one) and wrote a fraudulent settlement into the ledger.
    """
    engine, adapter, _, _, _, _ = await _open_long_position(
        database, quantity="1", ask_quantity="0.4"
    )
    try:
        entry = next(iter(adapter.orders.values()))
        local = await engine.order_manager.get_by_client(entry.client_order_id)
        assert local is not None
        # 0.4 of 1 filled: 0.6 of room remains, so a 0.2 fill is accepted by the
        # order's own invariants and only the routing guard can stop it.
        assert local.filled_quantity == Decimal("0.4")
        assert local.exchange_order_id is not None
        real_venue_id = local.exchange_order_id

        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-misrouted-partial",
                event_type=ExchangeEventType.ORDER_FILLED,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": "sim_ATTACKER_ORDER",
                    "client_order_id": entry.client_order_id,
                    "fill_id": "fill-wrong",
                    "fill_price": "50",
                    "fill_quantity": "0.2",
                    "status": "FILLED",
                },
            )
        )
        await engine.wait_for_event_queue()

        # STATE FIRST: on the vulnerable revision this is the assertion that
        # fails, and it fails in the EXPLOITED state (a larger filled quantity
        # and the attacker's venue id adopted over the real one) rather than on
        # a merely missing audit record.
        after = await engine.order_manager.get_by_client(entry.client_order_id)
        assert after.exchange_order_id == real_venue_id
        assert after.filled_quantity == Decimal("0.4")
        assert after.avg_fill_price == local.avg_fill_price
        # The real venue identity is still resolvable, and no bogus settlement
        # entered the ledger.
        assert (await engine.order_manager.get_by_exchange(real_venue_id)) is not None
        settlements = [
            row
            for row in await AuditService(database.session_factory).list_recent(limit=60)
            if row.action == "FILL_SETTLED"
        ]
        assert len(settlements) == 1

        mismatch = [
            row
            for row in await AuditService(database.session_factory).list_recent(limit=60)
            if row.action == "EXCHANGE_EVENT_ID_MISMATCH"
        ]
        assert len(mismatch) == 1
        assert (
            mismatch[0].after_json["reason"]
            == "LOCAL_ORDER_BOUND_TO_ANOTHER_VENUE_ORDER"
        )
        assert engine.exchange_event_identity_anomalies == 1
    finally:
        await engine.stop()


def _event_processing_ok(engine) -> bool | None:
    component = engine.health.snapshot()["components"].get("event_processing")
    return None if component is None else component["ok"]


async def test_L14_event_processing_health_recovers_after_an_anomaly(database):
    """R2: an anomaly is audited, and a genuine processing failure recovers.

    Two distinct outcomes are pinned:
      * an UNMATCHABLE event is durable evidence, not a health fault (the
        consumer is working, and one foreign/replayed event is not a component
        failure);
      * an event that actually FAILS to process marks health unhealthy and the
        next successfully processed event clears it, so a transient fault can
        never latch engine health for the life of the process.
    """
    engine, adapter, _, _, _, _ = await _open_long_position(database)
    try:
        audit = AuditService(database.session_factory)
        assert _event_processing_ok(engine) is True

        # (1) unmatchable event: audited, consumer still healthy.
        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-unknown",
                event_type=ExchangeEventType.ORDER_ACK,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": "sim_nope",
                    "client_order_id": "nope",
                    "symbol": "BTCUSDT",
                },
            )
        )
        await engine.wait_for_event_queue()
        assert [
            row for row in await audit.list_recent(limit=60)
            if row.action == "EXCHANGE_EVENT_UNMATCHED"
        ]
        assert _event_processing_ok(engine) is True

        # (2) an event that genuinely fails to process: unhealthy + audited.
        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-malformed",
                event_type=ExchangeEventType.MARKET_DELTA,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={"sequence": "not-an-integer", "bids": [], "asks": []},
            )
        )
        await engine.wait_for_event_queue()
        assert _event_processing_ok(engine) is False
        assert engine.health.snapshot()["overall"] == "UNHEALTHY"
        assert [
            row for row in await audit.list_recent(limit=60)
            if row.action == "EXCHANGE_EVENT_FAILED"
        ]

        # (3) the next good event recovers health; the evidence stays durable.
        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-balance-recover",
                event_type=ExchangeEventType.BALANCE_UPDATE,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={"balances": {"USDT": "10000"}},
            )
        )
        await engine.wait_for_event_queue()
        assert _event_processing_ok(engine) is True
        assert [
            row for row in await audit.list_recent(limit=60)
            if row.action == "EXCHANGE_EVENT_FAILED"
        ]
    finally:
        await engine.stop()


async def test_L15_account_scoped_balance_updates_are_reachable(database):
    """R5: a balance push carries no exchange order id and must still apply."""
    engine, adapter, _, _, _, _ = await _open_long_position(database)
    try:
        audit = AuditService(database.session_factory)
        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-balance-2",
                event_type=ExchangeEventType.BALANCE_UPDATE,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={"balances": {"USDT": "10000"}},
            )
        )
        await engine.wait_for_event_queue()

        unmatched = [
            row
            for row in await audit.list_recent(limit=40)
            if row.action in {"EXCHANGE_EVENT_UNMATCHED", "EXCHANGE_EVENT_ID_MISMATCH"}
        ]
        assert unmatched == []
    finally:
        await engine.stop()


async def test_L16_a_self_inconsistent_event_is_refused(database):
    """F-3: an event that resolves by its own venue id must still be consistent.

    A payload naming a different symbol, or a different client order, than the
    order its venue id resolves to would otherwise write a foreign fill into
    that order.
    """
    engine, adapter, _, _, _, _ = await _open_long_position(database)
    try:
        entry = next(iter(adapter.orders.values()))
        local = await engine.order_manager.get_by_client(entry.client_order_id)
        assert local is not None

        for event_id, payload, expected in (
            (
                "evt-symbol",
                {
                    "exchange_order_id": local.exchange_order_id,
                    "client_order_id": entry.client_order_id,
                    "symbol": "ETHUSDT",
                    "fill_id": "fill-sym",
                    "fill_price": "9999",
                    "fill_quantity": "1",
                    "status": "FILLED",
                },
                "EVENT_SYMBOL_DOES_NOT_MATCH_LOCAL_ORDER",
            ),
            (
                "evt-client",
                {
                    "exchange_order_id": local.exchange_order_id,
                    "client_order_id": "live_llm_foreign-order",
                    "symbol": "BTCUSDT",
                    "fill_id": "fill-cli",
                    "fill_price": "9999",
                    "fill_quantity": "1",
                    "status": "FILLED",
                },
                "EVENT_CLIENT_ID_DOES_NOT_MATCH_LOCAL_ORDER",
            ),
        ):
            await engine._enqueue_event(
                ExchangeEvent(
                    event_id=event_id,
                    event_type=ExchangeEventType.ORDER_FILLED,
                    symbol="BTCUSDT",
                    timestamp=datetime.now(UTC),
                    payload=payload,
                )
            )
            await engine.wait_for_event_queue()
            after = await engine.order_manager.get_by_client(entry.client_order_id)
            assert after.exchange_order_id == local.exchange_order_id
            assert after.filled_quantity == local.filled_quantity
            assert after.avg_fill_price == local.avg_fill_price
            reasons = {
                row.after_json["reason"]
                for row in await AuditService(database.session_factory).list_recent(limit=80)
                if row.action == "EXCHANGE_EVENT_ID_MISMATCH"
            }
            assert expected in reasons
        assert engine.exchange_event_identity_anomalies == 2
    finally:
        await engine.stop()


async def test_L17_identity_anomalies_are_counted_and_pageable(database):
    """F-4: a non-latching anomaly still has to be visible to an operator."""
    engine, adapter, _, _, _, _ = await _open_long_position(database)
    try:
        assert engine.runtime_snapshot()["exchange_event_identity_anomalies"] == 0
        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-foreign",
                event_type=ExchangeEventType.ORDER_ACK,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": "sim_foreign",
                    "client_order_id": "foreign-client",
                    "symbol": "BTCUSDT",
                },
            )
        )
        await engine.wait_for_event_queue()
        # Visible in the runtime snapshot even though health stays OK, so a
        # growing count is pageable without latching the engine unhealthy.
        assert engine.runtime_snapshot()["exchange_event_identity_anomalies"] == 1
        assert _event_processing_ok(engine) is True
    finally:
        await engine.stop()


async def test_L18_a_fill_arriving_before_the_venue_id_is_persisted_still_lands(database):
    """The root-cause contract, pinned WITHOUT depending on scheduling.

    L1 exercises the same window through a real submit, but whether an inline
    event is dequeued before the venue id is persisted is ultimately a
    scheduling outcome. This test removes that dependency entirely: it puts one
    order row into EXACTLY the race-window state (submitted locally, no venue id
    persisted) and dispatches the fill. Any future change that stops resolving
    events on the durable client_order_id fails here deterministically.
    """
    engine, adapter, _, _, plans, plan = await _open_long_position(database, race=False)
    try:
        intent = OrderIntent(
            client_order_id="live_llm_race-window-entry",
            strategy_id="live_llm",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("101"),
            metadata=dict(BTC_EXECUTION_METADATA, direction="LONG"),
        )
        order = await engine.order_manager.create_from_intent(
            intent, trading_mode=engine.settings.effective_mode()
        )
        await engine.order_manager.validate(order.internal_order_id)
        await engine.order_manager.submitting(order.internal_order_id)
        await engine.order_manager.submitted(order.internal_order_id)

        window_state = await engine.order_manager.get(order.internal_order_id)
        assert window_state is not None
        # This IS the window: the local row exists, the venue id does not.
        assert window_state.exchange_order_id is None
        assert window_state.client_order_id == order.client_order_id

        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-race-window-fill",
                event_type=ExchangeEventType.ORDER_FILLED,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": "sim_race_window_venue_id",
                    "client_order_id": order.client_order_id,
                    "symbol": "BTCUSDT",
                    "fill_id": "fill-race-window",
                    "fill_price": "100.05",
                    "fill_quantity": "0.05",
                    "status": "PARTIALLY_FILLED",
                },
            )
        )
        await engine.wait_for_event_queue()

        after = await engine.order_manager.get(order.internal_order_id)
        assert after is not None
        # The factual fill landed ...
        assert after.filled_quantity == Decimal("0.05")
        assert after.status == OrderStatus.PARTIALLY_FILLED
        # ... and the venue identity became durable as a result of processing it.
        assert after.exchange_order_id == "sim_race_window_venue_id"

        # A later event resolves by the now-durable venue id, and a duplicate of
        # the same logical fill must not double count.
        await engine._enqueue_event(
            ExchangeEvent(
                event_id="evt-race-window-fill-2",
                event_type=ExchangeEventType.ORDER_FILLED,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": "sim_race_window_venue_id",
                    "client_order_id": order.client_order_id,
                    "symbol": "BTCUSDT",
                    "fill_id": "fill-race-window-2",
                    "fill_price": "100.05",
                    "fill_quantity": "0.05",
                    "status": "FILLED",
                },
            )
        )
        await engine.wait_for_event_queue()
        final = await engine.order_manager.get(order.internal_order_id)
        assert final is not None
        assert final.filled_quantity == Decimal("0.1")
        assert final.status == OrderStatus.FILLED
        assert engine.exchange_event_identity_anomalies == 0
    finally:
        await engine.stop()


async def test_L19_a_symbol_naming_variant_is_not_refused(database):
    """R-1: the consistency guard must not reject LEGITIMATE events.

    Venues and the local book use different naming forms. A byte-exact symbol
    comparison would refuse every event for such an order - wedging the trade
    plan at APPROVED, the very symptom this fix removes. A payload that only
    differs in naming must be accepted; the event is what carries the fact.
    """
    engine, adapter, _, _, _, _ = await _open_long_position(database, race=False)
    try:
        intent = OrderIntent(
            client_order_id="live_llm_naming-variant",
            strategy_id="live_llm",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("101"),
            metadata=dict(BTC_EXECUTION_METADATA, direction="LONG"),
        )
        order = await engine.order_manager.create_from_intent(
            intent, trading_mode=engine.settings.effective_mode()
        )
        await engine.order_manager.validate(order.internal_order_id)
        await engine.order_manager.submitting(order.internal_order_id)
        await engine.order_manager.submitted(order.internal_order_id)

        for event_id, symbol_form in (
            ("evt-lowercase", "btcusdt"),
            ("evt-canonical", "BTCUSDT"),
        ):
            await engine._enqueue_event(
                ExchangeEvent(
                    event_id=event_id,
                    event_type=ExchangeEventType.ORDER_FILLED,
                    symbol="BTCUSDT",
                    timestamp=datetime.now(UTC),
                    payload={
                        # One order has ONE venue id: only the naming form varies.
                        "exchange_order_id": "sim_naming_venue_id",
                        "client_order_id": order.client_order_id,
                        # The only difference is the naming form.
                        "symbol": symbol_form,
                        "fill_id": f"fill-{event_id}",
                        "fill_price": "100.05",
                        "fill_quantity": "0.05",
                        "status": "PARTIALLY_FILLED",
                    },
                )
            )
            await engine.wait_for_event_queue()

            after = await engine.order_manager.get(order.internal_order_id)
            assert after is not None
            assert after.filled_quantity == (
                Decimal("0.05") if event_id == "evt-lowercase" else Decimal("0.1")
            ), f"event {event_id} was refused by the naming guard"

        assert engine.exchange_event_identity_anomalies == 0
    finally:
        await engine.stop()


# ==================================== §31 F6 restart recovery x lifecycle race
async def test_L20_restart_restore_then_live_events_are_never_dropped(database):
    """F6 restart recovery and the event-identity fix must not break each other.

    Two mechanisms meet at the restart boundary: F6 restores durable unresolved
    orders into the process-local PAPER broker, and the event path must never
    drop a venue event because a local identity was not visible. Both are
    exercised on ONE database across a real engine restart.

    Scope note: the venue fills applied in phase 3 are delivered as EVENTS (the
    venue executed them). They are deliberately not mirrored into the
    process-local simulator's own matcher, so this test asserts EVENT DELIVERY
    and identity resolution - not broker accounting. Driving a further local
    REDUCE afterwards would be rejected by the simulator's reduce-only guard,
    which is correct behaviour for a broker whose own book never saw that fill.
    """
    # ---- phase 1: a partially filled entry leaves an UNRESOLVED resting order
    engine_a, adapter_a, _, _, _, plan = await _open_long_position(
        database, ask_quantity="0.04", decision_id="restart-entry"
    )
    try:
        entry = next(iter(adapter_a.orders.values()))
        durable = await engine_a.order_manager.get_by_client(entry.client_order_id)
        assert durable is not None
        assert durable.status == OrderStatus.PARTIALLY_FILLED
        assert durable.quantity - durable.filled_quantity == Decimal("0.06")
        assert durable.exchange_order_id is not None
        venue_id = durable.exchange_order_id
        order_id = durable.internal_order_id
        client_order_id = durable.client_order_id
    finally:
        await engine_a.stop()

    # ---- phase 2: a NEW engine on the SAME database restores the order
    adapter_b = InlineEventDrainedAdapter(initial_balances={"USDT": Decimal("10000")})
    engine_b = make_paper_engine(database, engine_tick_seconds=3600, simulator=adapter_b)
    adapter_b.event_gate = engine_b._event_queue
    clock_b = MutableClock()
    engine_b.clock = clock_b
    await engine_b.start("run-restart-lifecycle")
    try:
        # F6 restored it into the process-local broker (identity + remaining qty).
        # The simulator keys its order book by venue id.
        restored = adapter_b.orders.get(venue_id)
        assert restored is not None, "F6 did not restore the unresolved order"
        assert restored.exchange_order_id == venue_id
        assert restored.quantity - restored.filled_quantity == Decimal("0.06")

        # The restored order is resolvable by BOTH identities - the contract the
        # event path depends on after a restart.
        assert (await engine_b.order_manager.get_by_exchange(venue_id)) is not None
        assert (await engine_b.order_manager.get_by_client(client_order_id)) is not None

        # ---- phase 3: the venue's post-restart event stream must all land
        for event_type, payload in (
            (ExchangeEventType.ORDER_ACK, {"status": "ACK", "filled_quantity": "0.04"}),
            (ExchangeEventType.ORDER_OPENED, {"status": "OPEN", "filled_quantity": "0.04"}),
            (
                ExchangeEventType.ORDER_FILLED,
                {
                    "status": "FILLED",
                    "fill_id": "fill-after-restart",
                    "fill_price": "100.05",
                    "fill_quantity": "0.06",
                    "filled_quantity": "0.1",
                },
            ),
        ):
            await engine_b._enqueue_event(
                ExchangeEvent(
                    event_id=f"evt-restart-{event_type.value}",
                    event_type=event_type,
                    symbol="BTCUSDT",
                    timestamp=datetime.now(UTC),
                    payload={
                        "exchange_order_id": venue_id,
                        "client_order_id": client_order_id,
                        "symbol": "BTCUSDT",
                        **payload,
                    },
                )
            )
            await engine_b.wait_for_event_queue()
            settled = await engine_b.order_manager.get(order_id)
            assert settled is not None

        # No event was dropped: the factual remaining fill is applied through
        # the whole post-restart stream.
        settled = await engine_b.order_manager.get(order_id)
        assert settled.filled_quantity == Decimal("0.1")
        assert settled.status == OrderStatus.FILLED
        position = await engine_b.portfolio.get_position("BTCUSDT")
        assert position is not None and position.quantity == Decimal("0.1")

        # ---- no event was merely tolerated anywhere across the restart
        anomalies = [
            row
            for row in await AuditService(database.session_factory).list_recent(limit=80)
            if row.action
            in {
                "EXCHANGE_EVENT_UNMATCHED",
                "EXCHANGE_EVENT_ID_MISMATCH",
                "EXCHANGE_EVENT_FAILED",
            }
        ]
        assert anomalies == [], [row.action for row in anomalies]
        assert engine_b.exchange_event_identity_anomalies == 0

        # A duplicate of an already-applied fill must not double count.
        await engine_b._enqueue_event(
            ExchangeEvent(
                event_id="evt-restart-duplicate",
                event_type=ExchangeEventType.ORDER_FILLED,
                symbol="BTCUSDT",
                timestamp=datetime.now(UTC),
                payload={
                    "exchange_order_id": venue_id,
                    "client_order_id": client_order_id,
                    "symbol": "BTCUSDT",
                    "fill_id": "fill-after-restart",
                    "fill_price": "100.05",
                    "fill_quantity": "0.06",
                    "status": "FILLED",
                },
            )
        )
        await engine_b.wait_for_event_queue()
        after_replay = await engine_b.order_manager.get(order_id)
        assert after_replay.filled_quantity == Decimal("0.1")
        assert engine_b.exchange_event_identity_anomalies == 0
        _ = plan
    finally:
        await engine_b.stop()
