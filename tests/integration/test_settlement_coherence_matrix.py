import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crypto_trader.domain.enums import ExchangeEventType, OrderSide, TradingMode
from crypto_trader.domain.errors import InvalidOrder, InvalidStateTransition, OrderRejected
from crypto_trader.domain.models import Fill, Instrument, OrderIntent
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    PositionLegService,
)
from crypto_trader.market_data.state import MarketState
from crypto_trader.order.manager import OrderManager
from crypto_trader.runtime.recovery import RecoveryService
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from tests.conftest import make_paper_engine
from tests.integration.test_settlement_generation_repro import DeliveryBarrierAdapter


class AccountReadBarrierAdapter(DeliveryBarrierAdapter):
    """Pause the external balance API, not local reconciliation collaborators."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pause_account_read = False
        self.account_read_started = asyncio.Event()
        self.release_account_read = asyncio.Event()

    async def get_balances(self):
        if self.pause_account_read:
            self.account_read_started.set()
            await self.release_account_read.wait()
        return await super().get_balances()

    async def get_market_state(self, symbol):
        book = await self.get_orderbook(symbol)
        return MarketState(
            symbol=symbol,
            provider="ISOLATED_FIXTURE",
            health="HEALTHY",
            best_bid=book.best_bid().price,
            best_ask=book.best_ask().price,
        )


@pytest.fixture
async def settlement_subject(database, request):
    adapter = AccountReadBarrierAdapter(
        instruments=[
            Instrument(
                symbol="NEARUSDT",
                base_asset="NEAR",
                quote_asset="USDT",
                instrument_type="LINEAR_PERP",
                contract_size="10",
            ),
            Instrument(
                symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type="LINEAR_PERP",
                contract_size="10",
            ),
        ]
    )
    engine = make_paper_engine(database, simulator=adapter, engine_tick_seconds=3600)
    if getattr(request.node, "callspec", None) is not None and (
        request.node.callspec.params.get("failed_table") == "POSITION_LEG_FILLS"
    ):
        from crypto_trader.execution.hedge_legs import LegPositionReconciler

        # Required dependencies must be assembled before factual startup;
        # injecting only a leg writer into a running engine is now fail-closed.
        engine.leg_service = PositionLegService(database.session_factory)
        engine.leg_reconciler = LegPositionReconciler(engine.leg_service)
    # Real runtime initialization, including current safety state; no mocked
    # "healthy" authorization predicate for the coordinator regressions.
    await engine.start()
    local_orders = {}

    async def receive(event):
        local = local_orders.get(event.payload.get("client_order_id"))
        if local is None:
            return
        if event.event_type == ExchangeEventType.ORDER_ACK:
            await engine.order_manager.ack(
                local.internal_order_id, event.payload["exchange_order_id"]
            )
        else:
            await engine.process_exchange_event(event)

    await adapter.subscribe_order_updates(receive)

    async def submit(
        client,
        quantity="0.6",
        side=OrderSide.BUY,
        reduce=False,
        depth="1",
        symbol="NEARUSDT",
        price=None,
        leg_id=None,
    ):
        book = adapter.seed_book(symbol, mid="5.117", spread="0.001")
        book.apply_snapshot(
            2, [(Decimal("5.116"), Decimal(depth))], [(Decimal("5.118"), Decimal(depth))]
        )
        local = await engine.order_manager.create_from_intent(
            OrderIntent(
                client_order_id=client,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price or ("5.128" if side == OrderSide.BUY else "5.1"),
                metadata={
                    "instrument_type": "LINEAR_PERP",
                    "contract_size": "10",
                    "reduce_only": reduce,
                    **({"leg_id": leg_id} if leg_id else {}),
                },
            ),
            trading_mode=TradingMode.PAPER,
        )
        local_orders[client] = local
        await engine.order_manager.validate(local.internal_order_id)
        await engine.order_manager.submitting(local.internal_order_id)
        await engine.order_manager.submitted(local.internal_order_id)
        external = await adapter.submit_order(local)
        await engine.wait_for_event_queue()
        return local, external

    yield engine, adapter, submit
    await engine.stop()


async def test_settlement_begins_during_external_account_read(settlement_subject):
    engine, adapter, submit = settlement_subject
    adapter.pause_account_read = True
    comparison = asyncio.create_task(engine.reconciliation.reconcile(adapter))
    submission = None
    try:
        await asyncio.wait_for(adapter.account_read_started.wait(), 5)
        adapter.pause_delivery = True
        submission = asyncio.create_task(submit("begins-during-reconcile"))
        await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
        adapter.release_account_read.set()
        report = await asyncio.wait_for(comparison, 5)
        assert report.state == "PENDING_SETTLEMENT"
        assert not report.ok and not report.halt
        assert report.alerts == [] and report.positions_diff == {}
    finally:
        adapter.release_account_read.set()
        adapter.release_delivery.set()
        await asyncio.wait_for(comparison, 5)
        if submission is not None:
            await asyncio.wait_for(submission, 5)
    adapter.pause_account_read = False
    assert (await engine.reconciliation.reconcile(adapter)).ok
    assert engine.settlement.snapshot()["state"] == "COHERENT"


async def test_duplicate_delivery_does_not_fault_or_post_twice(settlement_subject):
    engine, adapter, submit = settlement_subject
    adapter.duplicate_fill = True
    local, external = await submit("duplicate")
    assert engine.settlement.snapshot()["state"] == "COHERENT", engine.settlement.snapshot()
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    assert (await engine.order_manager.get(local.internal_order_id)).filled_quantity == Decimal(
        "0.6"
    )
    report = await engine.reconciliation.reconcile(adapter)
    assert report.ok and not report.halt


@pytest.mark.parametrize("iteration", range(10))
async def test_different_symbol_resting_fills_share_one_account_fence(
    settlement_subject, iteration
):
    engine, adapter, submit = settlement_subject
    first, first_external = await submit("resting-near", price="5.1")
    second, second_external = await submit("resting-btc", symbol="BTCUSDT", price="5.1")
    assert first_external.filled_quantity == second_external.filled_quantity == 0
    assert (await engine.reconciliation.reconcile(adapter)).ok
    for symbol in ("NEARUSDT", "BTCUSDT"):
        adapter.seed_book(symbol, mid="5.09", spread="0.001")
    # Previously accepted orders later match their actual fixture books; account
    # mutation precedes delivery to the real event/ledger/projection pipeline.
    groups = await asyncio.wait_for(
        asyncio.gather(
            adapter._match_guarded(first_external), adapter._match_guarded(second_external)
        ),
        5,
    )
    pending = await engine.reconciliation.reconcile(adapter)
    assert pending.state == "PENDING_SETTLEMENT" and not pending.ok and not pending.halt
    assert pending.positions_diff == {} and pending.alerts == []
    assert await engine.portfolio.get_positions() == {}
    assert {p.symbol: p.quantity for p in await adapter.get_positions()} == {
        "NEARUSDT": Decimal("0.6"),
        "BTCUSDT": Decimal("0.6"),
    }
    await asyncio.wait_for(
        asyncio.gather(*(adapter._emit(e) for group in groups for e in group)), 5
    )
    await asyncio.wait_for(engine.wait_for_event_queue(), 5)
    for order in (first, second):
        assert (await engine.order_manager.get(order.internal_order_id)).filled_quantity == Decimal(
            "0.6"
        )
    assert {p.symbol: p.quantity for p in (await engine.portfolio.get_positions()).values()} == {
        "NEARUSDT": Decimal("0.6"),
        "BTCUSDT": Decimal("0.6"),
    }
    snapshot = engine.settlement.snapshot()
    if snapshot["state"] != "COHERENT":
        pytest.fail("different-symbol settlement: " + repr(snapshot))
    assert (await engine.reconciliation.reconcile(adapter)).ok


async def test_cancel_race_uses_fenced_market_derived_remaining_fill(settlement_subject):
    engine, adapter, submit = settlement_subject
    local, external = await submit("cancel-race", depth="0.3")
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.3")
    adapter.seed_book("NEARUSDT", mid="5.117", spread="0.001")
    adapter.cancel_fill_race = True  # Isolated chaos control, never production.
    adapter.pause_delivery = True
    cancellation = asyncio.create_task(adapter.cancel_order("NEARUSDT", external.exchange_order_id))
    try:
        await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
        report = await engine.reconciliation.reconcile(adapter)
        assert report.state == "PENDING_SETTLEMENT" and not report.halt
        assert (await adapter.get_positions())[0].quantity == Decimal("0.6")
    finally:
        adapter.release_delivery.set()
        await asyncio.wait_for(cancellation, 5)
        await engine.wait_for_event_queue()
    assert (await engine.order_manager.get(local.internal_order_id)).filled_quantity == Decimal(
        "0.6"
    )
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    assert (await engine.reconciliation.reconcile(adapter)).ok
    assert engine.settlement.snapshot()["state"] == "COHERENT"


async def test_late_completed_fill_delivery_cannot_double_post(settlement_subject):
    engine, adapter, submit = settlement_subject
    local, _ = await submit("late-completed-duplicate")
    entries_before = await engine.ledger.list_entries_recent(limit=200)
    actual_fills = [e for e in adapter.event_log if e.event_type == ExchangeEventType.ORDER_FILLED]
    assert actual_fills
    for actual_event in actual_fills:
        await adapter._emit(actual_event)
    await engine.wait_for_event_queue()
    entries_after = await engine.ledger.list_entries_recent(limit=200)
    assert {e.entry_id for e in entries_after} == {e.entry_id for e in entries_before}
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    assert (await engine.order_manager.get(local.internal_order_id)).filled_quantity == Decimal(
        "0.6"
    )
    assert engine.settlement.snapshot()["state"] == "COHERENT"
    assert (await engine.reconciliation.reconcile(adapter)).ok


async def test_orphan_recovery_preserves_factual_position_without_invented_close(
    settlement_subject,
):
    engine, adapter, submit = settlement_subject
    await submit("orphan-factual-fixture")
    orders_before = await engine.order_manager.list_all()
    entries_before = await engine.ledger.list_entries_recent(limit=200)
    assert await engine.trade_plans.get_active_for_symbol("NEARUSDT") is None
    actions = await RecoveryService(
        engine.order_manager,
        adapter,
        engine.audit,
        positions_provider=engine.portfolio.get_positions,
        plans=engine.trade_plans,
    ).recover("isolated-orphan-recovery")
    assert len(await engine.order_manager.list_all()) == len(orders_before)
    assert {e.entry_id for e in await engine.ledger.list_entries_recent(limit=200)} == {
        e.entry_id for e in entries_before
    }
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    assert (await adapter.get_positions())[0].quantity == Decimal("0.6")
    assert any("ORPHAN_POSITION_UNRESOLVED" in action for action in actions)
    assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
    assert engine.trading_safety_failures()


@pytest.mark.parametrize(
    "failed_table", ["LEDGER_TRANSACTIONS", "POSITIONS_PROJECTION", "POSITION_LEG_FILLS"]
)
async def test_durable_write_failure_remains_faulted_after_late_duplicate(
    database, settlement_subject, failed_table
):
    engine, adapter, submit = settlement_subject
    failed_writes = []
    if failed_table == "POSITION_LEG_FILLS":
        registered = await engine.leg_service.register(
            HedgeLegContract(
                leg_id="fixture-leg",
                symbol="NEARUSDT",
                side="LONG",
                kind=LegKind.ENTRY,
                strategy="FIXTURE",
                thesis="isolated leg durability fixture",
                base_exit={"type": "PRICE", "trigger": ">=1"},
                invalidation="fixture invalidation",
                evidence_families=["trend"],
                reason="isolated durability fixture",
            )
        )
        assert registered.allowed is True

    def fail_ledger_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO " + failed_table):
            failed_writes.append(True)
            raise RuntimeError("isolated ledger durability failure")

    event.listen(database.engine.sync_engine, "before_cursor_execute", fail_ledger_insert)
    try:
        local, _ = await submit(
            "ledger-write-failure",
            leg_id="fixture-leg" if failed_table == "POSITION_LEG_FILLS" else None,
        )
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", fail_ledger_insert)
    assert failed_writes
    assert (await engine.order_manager.get(local.internal_order_id)).filled_quantity == Decimal(
        "0.6"
    )
    assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
    assert engine.trading_safety_failures()
    # Replay the actual exchange event after the database recovers, not an
    # invented new fill. Durable fill existence alone cannot clear the fault.
    fill_events = [e for e in adapter.event_log if e.event_type == ExchangeEventType.ORDER_FILLED]
    assert fill_events
    for actual_event in fill_events:
        await adapter._emit(actual_event)
    await engine.wait_for_event_queue()
    report = await engine.reconciliation.reconcile(adapter)
    assert report.state == "SETTLEMENT_FAULT" and report.halt and not report.ok
    assert engine.settlement.snapshot()["faults"]


async def test_crash_before_fill_durability_cannot_restart_healthy(database, settlement_subject):
    engine, adapter, submit = settlement_subject
    adapter.pause_delivery = True
    task = asyncio.create_task(submit("crash"))
    await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
    task.cancel()  # Isolated process-loss model; no production process touched.
    with pytest.raises(asyncio.CancelledError):
        await task
    await engine.stop()
    restarted = make_paper_engine(database, simulator=SimulatedExchangeAdapter())
    await restarted.start()
    try:
        snapshot = restarted.runtime_snapshot()
        assert snapshot["settlement"]["state"] == "SETTLEMENT_FAULT"
        assert snapshot["health"]["overall"] == "UNHEALTHY"
    finally:
        await restarted.stop()


async def test_sequential_partial_fill_never_exceeds_order_quantity(settlement_subject):
    engine, adapter, submit = settlement_subject
    local, external = await submit("partials", depth="0.3")
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.3")
    assert engine.settlement.snapshot()["state"] == "COHERENT"
    adapter.seed_book("NEARUSDT", mid="5.117", spread="0.001")
    events = await adapter._match_guarded(external)
    for external_event in events:
        await adapter._emit(external_event)
    await engine.wait_for_event_queue()
    assert engine.settlement.snapshot()["faults"] == {}
    assert engine.settlement.snapshot()["state"] == "COHERENT", engine.settlement.snapshot()
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    assert (await engine.order_manager.get(local.internal_order_id)).filled_quantity == Decimal(
        "0.6"
    )
    report = await engine.reconciliation.reconcile(adapter)
    assert report.ok and not report.halt


async def test_canonical_restore_is_a_generation_change(settlement_subject):
    engine, adapter, _ = settlement_subject
    generation = engine.settlement.generation
    await adapter.restore_from_canonical_state(balances={"USDT": Decimal("100000")}, positions={})
    assert engine.settlement.generation > generation
    assert engine.settlement.snapshot()["state"] == "COHERENT"


async def test_real_same_generation_mismatch_still_halts(settlement_subject):
    engine, adapter, submit = settlement_subject
    await submit("true-mismatch")
    # Canonical hydration supplies a deliberately divergent isolated exchange
    # account. It is not a concurrent settlement and must not hide a real fault.
    position = (await adapter.get_positions())[0]
    await adapter.restore_from_canonical_state(
        balances=adapter.balances,
        positions={"NEARUSDT": position.model_copy(update={"quantity": Decimal("0.3")})},
    )
    report = await engine.reconciliation.reconcile(adapter)
    assert not report.ok and report.halt
    assert report.state == "COHERENT_MISMATCH"
    assert report.positions_diff["NEARUSDT"] == {
        "local_quantity": "0.6",
        "exchange_quantity": "0.3",
    }


async def test_new_order_rejected_during_delivery(settlement_subject):
    engine, adapter, submit = settlement_subject
    adapter.pause_delivery = True
    task = asyncio.create_task(submit("pending"))
    try:
        await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
        with pytest.raises(Exception, match="settlement account not coherent"):
            await submit("must-not-spawn")
        assert len(adapter.orders) == 1
        assert engine.settlement.snapshot()["state"] == "PENDING_SETTLEMENT"
    finally:
        adapter.release_delivery.set()
        await asyncio.wait_for(task, 5)


async def test_stuck_external_fill_is_stale_not_a_coherent_mismatch(
    settlement_subject, monkeypatch
):
    engine, adapter, submit = settlement_subject
    adapter.pause_delivery = True
    task = asyncio.create_task(submit("stuck-delivery"))
    try:
        await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
        now = engine.settlement.clock()
        monkeypatch.setattr(engine.settlement, "clock", lambda: now + 121)
        report = await engine.reconciliation.reconcile(adapter)
        assert report.state == "SETTLEMENT_STALE" and report.halt and not report.ok
        assert report.checked_at is None and report.positions_diff == {} and report.alerts == []
        assert "SETTLEMENT_NOT_COHERENT" in engine.trading_safety_failures()
    finally:
        adapter.release_delivery.set()
        await asyncio.wait_for(task, 5)
    assert engine.settlement.snapshot()["state"] == "COHERENT"
    assert (await engine.reconciliation.reconcile(adapter)).ok


async def test_completed_durable_batch_can_restart_coherently(database, settlement_subject):
    engine, adapter, submit = settlement_subject
    await submit("complete-before-restart")
    # This low-level settlement fixture has no Chief plan. Close it through
    # actual native matching before restart; an open plan-less position now
    # correctly fails the separate orphan safety gate, tested above.
    await submit("complete-exit-before-restart", side=OrderSide.SELL, reduce=True)
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == 0
    await engine.stop()
    restarted = make_paper_engine(
        database, simulator=SimulatedExchangeAdapter(instruments=list(adapter.instruments.values()))
    )
    await restarted.start()
    try:
        assert restarted.settlement.snapshot()["state"] == "COHERENT"
        assert (await restarted.portfolio.get_position("NEARUSDT")).quantity == 0
        report = await restarted.reconciliation.reconcile(restarted.adapter)
        assert report.ok and not report.halt
    finally:
        await restarted.stop()


async def test_concurrent_duplicate_fill_database_race_is_idempotent(database, settlement_subject):
    engine, adapter, submit = settlement_subject
    adapter.pause_delivery = True
    submission = asyncio.create_task(submit("durable-duplicate-race"))
    await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
    local = await engine.order_manager.get_by_client("durable-duplicate-race")
    fill = engine._fill_from_payload(local, adapter.paused_event.payload)
    both_reads = asyncio.Event()
    reads = 0

    class ReadBarrierSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            nonlocal reads
            result = await super().execute(statement, *args, **kwargs)
            sql = str(statement)
            if reads < 2 and "FROM fills" in sql and "fills.fill_id" in sql:
                reads += 1
                if reads == 2:
                    both_reads.set()
                await asyncio.wait_for(both_reads.wait(), 5)
            return result

    # Two actual DB reads observe the same absent fill before either writes.
    # No internal order/ledger/authority result is mocked or replaced.
    factory = async_sessionmaker(database.engine, class_=ReadBarrierSession, expire_on_commit=False)
    manager = OrderManager(factory, settlement_callback=engine._settle_fill)
    manager.settlement_coordinator = engine.settlement
    try:
        results = await asyncio.wait_for(
            asyncio.gather(manager.apply_fill(fill), manager.apply_fill(fill)), 5
        )
        assert sorted(result[2] for result in results) == [False, True]
        assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    finally:
        adapter.release_delivery.set()
        await asyncio.wait_for(submission, 5)
    assert engine.settlement.snapshot()["state"] == "COHERENT"
    assert (await engine.reconciliation.reconcile(adapter)).ok


async def test_duplicate_absent_read_then_completed_order_is_idempotent(
    database, settlement_subject
):
    engine, adapter, submit = settlement_subject
    adapter.pause_delivery = True
    submission = asyncio.create_task(submit("absent-then-completed"))
    await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
    local = await engine.order_manager.get_by_client("absent-then-completed")
    fill = engine._fill_from_payload(local, adapter.paused_event.payload)
    absent_read = asyncio.Event()
    release_read = asyncio.Event()

    class AbsentReadBarrier(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            sql = str(statement)
            if not absent_read.is_set() and "FROM fills" in sql and "fills.fill_id" in sql:
                absent_read.set()
                await asyncio.wait_for(release_read.wait(), 5)
            return result

    factory = async_sessionmaker(database.engine, class_=AbsentReadBarrier, expire_on_commit=False)
    delayed = OrderManager(factory, settlement_callback=engine._settle_fill)
    delayed.settlement_coordinator = engine.settlement
    duplicate = asyncio.create_task(delayed.apply_fill(fill))
    try:
        await asyncio.wait_for(absent_read.wait(), 5)
        assert (await engine.order_manager.apply_fill(fill))[2] is True
        entries = await engine.ledger.list_entries_recent(limit=200)
        release_read.set()
        assert (await asyncio.wait_for(duplicate, 5))[2] is False
        assert {e.entry_id for e in await engine.ledger.list_entries_recent(limit=200)} == {
            e.entry_id for e in entries
        }
    finally:
        release_read.set()
        adapter.release_delivery.set()
        await asyncio.wait_for(submission, 5)
    assert engine.settlement.snapshot()["state"] == "COHERENT"
    assert (await engine.reconciliation.reconcile(adapter)).ok


async def test_new_overfill_is_not_misclassified_as_completed_duplicate(settlement_subject):
    engine, adapter, submit = settlement_subject
    local, _ = await submit("overfill-negative-control")
    actual = next(e for e in adapter.event_log if e.event_type == ExchangeEventType.ORDER_FILLED)
    invalid = engine._fill_from_payload(local, actual.payload).model_copy(
        update={"fill_id": "isolated-invalid-new-overfill"}
    )
    entries = await engine.ledger.list_entries_recent(limit=200)
    with pytest.raises(InvalidStateTransition, match="exceeds remaining"):
        await engine.order_manager.apply_fill(invalid)
    assert await engine.order_manager.get_fill(invalid.fill_id) is None
    assert {e.entry_id for e in await engine.ledger.list_entries_recent(limit=200)} == {
        e.entry_id for e in entries
    }
    assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"


async def test_leg_attributed_fill_without_required_leg_service_retains_fault(
    settlement_subject,
):
    """A leg fill must never publish settlement without its required allocation."""
    engine, adapter, submit = settlement_subject
    assert engine.leg_service is None
    local, _ = await submit("leg-service-missing", leg_id="fixture-leg")
    fill_events = [e for e in adapter.event_log if e.event_type == ExchangeEventType.ORDER_FILLED]
    assert fill_events
    audits = await engine.audit.list_recent(limit=200)
    assert any(a.action == "LEG_ALLOCATION_UNAVAILABLE" for a in audits)
    assert not any(
        a.action == "FILL_SETTLED" and a.target == fill_events[-1].payload["fill_id"]
        for a in audits
    )
    assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
    assert "SETTLEMENT_NOT_COHERENT" in engine.trading_safety_failures()
    report = await engine.reconciliation.reconcile(adapter)
    assert report.state == "SETTLEMENT_FAULT" and report.halt and not report.ok
    assert (await engine.order_manager.get(local.internal_order_id)).filled_quantity == Decimal(
        "0.6"
    )


async def test_settlement_callback_missing_order_fails_closed(settlement_subject):
    engine, _, _ = settlement_subject
    fill = Fill(
        fill_id="isolated-missing-order-fill",
        order_id="ord-does-not-exist",
        client_order_id="isolated-missing-order",
        symbol="NEARUSDT",
        side=OrderSide.BUY,
        price=Decimal("5.128"),
        quantity=Decimal("0.6"),
        fee=Decimal("0"),
        timestamp=datetime.now(UTC),
    )
    engine.settlement.begin(fill.fill_id, "ISOLATED_FIXTURE")
    with pytest.raises(ValueError, match="SETTLEMENT_ORDER_MISSING"):
        await engine._settle_fill(fill)


async def test_concurrent_distinct_fills_same_account_are_each_settled_once(settlement_subject):
    engine, adapter, submit = settlement_subject
    first, first_external = await submit("same-symbol-resting-a", quantity="0.3", price="5.1")
    second, second_external = await submit("same-symbol-resting-b", quantity="0.3", price="5.1")
    assert first_external.filled_quantity == second_external.filled_quantity == 0
    assert (await engine.reconciliation.reconcile(adapter)).ok
    adapter.seed_book("NEARUSDT", mid="5.09", spread="0.001")
    groups = await asyncio.wait_for(
        asyncio.gather(
            adapter._match_guarded(first_external), adapter._match_guarded(second_external)
        ),
        5,
    )
    pending = await engine.reconciliation.reconcile(adapter)
    assert pending.state == "PENDING_SETTLEMENT" and not pending.ok and not pending.halt
    assert pending.positions_diff == {} and pending.alerts == []
    await asyncio.wait_for(
        asyncio.gather(*(adapter._emit(event) for group in groups for event in group)), 5
    )
    await asyncio.wait_for(engine.wait_for_event_queue(), 5)
    assert (await engine.order_manager.get(first.internal_order_id)).filled_quantity == Decimal(
        "0.3"
    )
    assert (await engine.order_manager.get(second.internal_order_id)).filled_quantity == Decimal(
        "0.3"
    )
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    entries = await engine.ledger.list_entries_recent(limit=200)
    fill_ids = [
        event.payload["fill_id"]
        for group in groups
        for event in group
        if event.event_type == ExchangeEventType.ORDER_FILLED
    ]
    assert len(fill_ids) == len(set(fill_ids)) == 2
    assert engine.settlement.snapshot()["state"] == "COHERENT", engine.settlement.snapshot()
    assert (await engine.reconciliation.reconcile(adapter)).ok
    assert entries


async def test_unfenced_external_account_mutation_is_rejected_and_faulted(settlement_subject):
    engine, adapter, _ = settlement_subject
    instrument = adapter.instruments["NEARUSDT"]
    fill = Fill(
        fill_id="isolated-unfenced-mutation",
        order_id="ord-unfenced",
        client_order_id="isolated-unfenced",
        symbol="NEARUSDT",
        side=OrderSide.BUY,
        price=Decimal("5.1"),
        quantity=Decimal("0.1"),
        fee=Decimal("0"),
        timestamp=datetime.now(UTC),
    )
    with pytest.raises(InvalidOrder, match="outside settlement batch"):
        adapter._apply_fill_to_balances(fill, instrument)
    snapshot = engine.settlement.snapshot()
    assert snapshot["state"] == "SETTLEMENT_FAULT"
    assert snapshot["faults"][fill.fill_id] == "UNFENCED_EXTERNAL_MUTATION"
    assert "SETTLEMENT_NOT_COHERENT" in engine.trading_safety_failures()


async def test_deadlock_regression_concurrent_fence_reconcile_and_submit(settlement_subject):
    """Settlement, reconciliation and a fenced submission must not block each other."""
    engine, adapter, submit = settlement_subject
    adapter.pause_account_read = True
    comparison = asyncio.create_task(engine.reconciliation.reconcile(adapter))
    await asyncio.wait_for(adapter.account_read_started.wait(), 5)
    adapter.pause_delivery = True
    delivery = asyncio.create_task(submit("deadlock-fill"))
    try:
        await asyncio.wait_for(adapter.external_fill_applied.wait(), 5)
        adapter.release_account_read.set()
        report = await asyncio.wait_for(comparison, 5)
        assert report.state == "PENDING_SETTLEMENT" and not report.ok and not report.halt
        # The native PAPER acceptance guard rejects the new order without
        # waiting on any settlement lock.
        with pytest.raises(OrderRejected, match="settlement account not coherent"):
            await asyncio.wait_for(submit("deadlock-probe"), 5)
    finally:
        adapter.release_account_read.set()
        adapter.pause_delivery = False
        adapter.release_delivery.set()
        await asyncio.wait_for(delivery, 5)
    local = await engine.order_manager.get_by_client("deadlock-fill")
    assert local is not None and local.filled_quantity == Decimal("0.6")
    assert engine.settlement.snapshot()["state"] == "COHERENT"
    assert (await engine.reconciliation.reconcile(adapter)).ok
