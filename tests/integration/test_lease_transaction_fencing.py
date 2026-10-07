"""Actual core services cannot write with expired or superseded authority."""

import asyncio
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.util import await_only

from crypto_trader.api.app import create_app
from crypto_trader.domain.enums import TradingMode
from crypto_trader.domain.errors import LeaseNotHeld, OrderRejected
from crypto_trader.persistence.models import AuditEventORM
from crypto_trader.runtime.lease import LeaseManager
from tests.conftest import make_paper_engine
from tests.integration.test_api import make_state
from tests.integration.test_order_manager import make_intent


async def test_cancelled_fence_statement_does_not_retain_the_sqlite_writer_lock(
    database, monkeypatch
):
    import aiosqlite

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("cancelled-fence-lock")
    paused = asyncio.Event()
    original_execute = aiosqlite.Cursor.execute
    retained_cursors = []

    async def cancel_window(cursor, sql, parameters=None):
        result = await original_execute(cursor, sql, parameters)
        if (not retained_cursors
                and sql.startswith("UPDATE runtime_leases SET version=runtime_leases.version")):
            retained_cursors.append(cursor)  # A cancelled task/traceback can retain this cursor.
            paused.set()
            await asyncio.Event().wait()
        return result

    monkeypatch.setattr(aiosqlite.Cursor, "execute", cancel_window)
    writer = asyncio.create_task(engine.order_manager.create_from_intent(
        make_intent("cancel-during-fence"), trading_mode=TradingMode.PAPER,
    ))
    try:
        await asyncio.wait_for(paused.wait(), 5)
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer
        # Keep the cancelled cursor alive through the real shutdown writes.
        assert retained_cursors
        await asyncio.wait_for(engine.stop(), 2)
        assert await engine.order_manager.list_all() == []
    finally:
        # Diagnostic cleanup only; no production connection/row is involved.
        retained_cursors.clear()
        await engine.stop()


async def test_inflight_current_probe_cannot_clear_latched_lease_loss(database, monkeypatch):
    from crypto_trader.llm_chief.decision_store import LLMDecisionStore
    from crypto_trader.trade_plan.service import TradePlanService
    from tests.integration.test_trading_safety_gate import _fresh_entry_signal

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("probe-cannot-restore-authority")
    await engine._strategy_context("BTCUSDT")
    _, signal = await _fresh_entry_signal(
        engine, LLMDecisionStore(engine.session_factory), TradePlanService(engine.session_factory),
        "queued-probe-race",
    )
    actual_query = engine.lease_manager.is_current

    async def current_but_loss_during_await(*args, **kwargs):
        current = await actual_query(*args, **kwargs)
        assert current is True
        engine._lose_execution_lease()  # Same callback used by actual writer/renewal failure.
        return current

    monkeypatch.setattr(engine.lease_manager, "is_current", current_but_loss_during_await)
    try:
        try:
            await engine.process_signal(signal)
        except (LeaseNotHeld, OrderRejected):
            pass
        assert engine.execution_lease_current() is False
        assert await engine.order_manager.list_all() == []
    finally:
        await engine.stop()


async def test_execution_adapter_cannot_be_rebound_to_another_actor(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("adapter-owner-a")
    try:
        with pytest.raises(LeaseNotHeld, match="adapter"):
            make_paper_engine(database, simulator=engine.adapter, engine_tick_seconds=3600)
        assert engine.adapter.execution_guard.__self__ is engine
        assert engine.adapter.lease_mutation_guard.__self__ is engine
        assert engine.settlement.journal.__self__ is engine
    finally:
        await engine.stop()


async def test_waiting_native_submit_cannot_borrow_a_restarted_actors_guard(database, monkeypatch):
    first = make_paper_engine(database, engine_tick_seconds=3600)
    await first.start("native-old-actor")
    order = await first.order_manager.create_from_intent(
        make_intent("waiting-old-actor"), trading_mode=TradingMode.PAPER,
    )
    paused, release = asyncio.Event(), asyncio.Event()
    original_sleep = asyncio.sleep

    async def paused_submit_clock(delay):
        if delay == 0.1234:
            paused.set()
            await release.wait()
        else:
            await original_sleep(delay)

    first.adapter.submit_delay_seconds = 0.1234
    monkeypatch.setattr("crypto_trader.simulator.exchange.asyncio.sleep", paused_submit_clock)
    pending = asyncio.create_task(first.adapter.submit_order(order))
    second = None
    try:
        await asyncio.wait_for(paused.wait(), 5)
        await first.stop()
        second = make_paper_engine(
            database, simulator=first.adapter, engine_tick_seconds=3600,
        )
        await second.start("native-new-actor")
        assert second.execution_lease_current() is True
        release.set()
        with pytest.raises(OrderRejected):
            await asyncio.wait_for(pending, 5)
        assert first.adapter.orders == {}
        with pytest.raises(LeaseNotHeld, match="adapter"):
            await first.start("cannot-reclaim-rebound-adapter")
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        if second is not None:
            await second.stop()
        await first.stop()


@pytest.mark.parametrize("mutation", ["delete", "mode"])
async def test_lost_lease_shutdown_exception_cannot_delete_or_repurpose_run(database, mutation):
    from crypto_trader.persistence.models import EngineRunORM

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("shutdown-metadata-only")
    await engine.stop()
    async with engine.session_factory() as session:
        row = await session.get(EngineRunORM, engine.run_id)
        assert row.state == "STOPPED"
        if mutation == "delete":
            await session.delete(row)
        else:
            row.mode = "LIVE"
        with pytest.raises(LeaseNotHeld):
            await session.commit()


async def test_projection_refresh_cannot_overwrite_a_concurrent_committed_trade(database):
    """Pause the real DB read; concurrent real ledger writes must stay fenced."""
    from crypto_trader.domain.enums import LedgerEntryType, OrderSide
    from crypto_trader.ledger.service import build_trade_entries

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("projection-snapshot-fence")

    async def trade(symbol):
        postings, metadata = build_trade_entries(
            side=OrderSide.BUY, symbol=symbol, quote_currency="USDT",
            price=Decimal("1"), quantity=Decimal("1"), fee=Decimal("0"),
        )
        await engine.ledger.record(LedgerEntryType.TRADE, postings, metadata=metadata)
        await engine.portfolio.refresh()

    await trade("NEARUSDT")
    read_started, release_read = asyncio.Event(), asyncio.Event()
    armed = True

    def pause_first_ledger_read(_conn, _cursor, statement, _params, _context, _many):
        nonlocal armed
        if armed and statement.startswith("SELECT ledger_transactions."):
            armed = False
            read_started.set()
            await_only(release_read.wait())  # Real SQLite boundary, not a fake replay.

    event.listen(database.engine.sync_engine, "after_cursor_execute", pause_first_ledger_read)
    tasks = []
    try:
        tasks.append(asyncio.create_task(engine.portfolio.refresh()))
        await asyncio.wait_for(read_started.wait(), 5)
        tasks.append(asyncio.create_task(trade("BTCUSDT")))
        # A fenced reader holds the writer lock; an unfenced old snapshot lets
        # the second trade publish first and then overwrites it with NEAR only.
        await asyncio.wait([tasks[-1]], timeout=0.3)
        release_read.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        positions = await engine.portfolio.get_positions()
        assert {p.symbol: p.quantity for p in positions.values()} == {
            "NEARUSDT": Decimal("1"), "BTCUSDT": Decimal("1"),
        }
    finally:
        release_read.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        event.remove(database.engine.sync_engine, "after_cursor_execute", pause_first_ledger_read)
        await engine.stop()


async def test_expired_writer_cannot_create_durable_order(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("expired-write")
    try:
        status = await engine.lease_manager.status(engine.lease_key)
        monkeypatch.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
        # No central check: the actual DB mutation must independently fence.
        with pytest.raises(LeaseNotHeld):
            await engine.order_manager.create_from_intent(
                make_intent("expired-authority"), trading_mode=TradingMode.PAPER,
            )
        assert await engine.order_manager.list_all() == []
    finally:
        await engine.stop()


async def test_rejected_writer_cannot_resume_using_old_grant_after_clock_recovery(
    database, monkeypatch
):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("writer-fault-latched")
    try:
        status = await engine.lease_manager.status(engine.lease_key)
        with monkeypatch.context() as clock:
            clock.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
            with pytest.raises(LeaseNotHeld):
                await engine.order_manager.create_from_intent(
                    make_intent("old-grant-expired"), trading_mode=TradingMode.PAPER,
                )
        assert engine.lease_manager.is_current_now(engine.lease) is True
        assert "EXECUTION_LEASE_NOT_HELD" in engine.trading_safety_failures()
        assert engine.risk_engine.kill_switch.enabled is True
        assert await engine.order_manager.list_all() == []
    finally:
        await engine.stop()


@pytest.mark.parametrize("path", ["chief", "manual", "perpetual"])
async def test_expired_lease_blocks_all_supported_risk_entry_paths(database, monkeypatch, path):
    from crypto_trader.llm_chief.decision_store import LLMDecisionStore
    from crypto_trader.trade_plan.service import TradePlanService
    from tests.integration.test_trading_safety_gate import _fresh_entry_signal

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("queued-expiry-" + path)
    await engine._strategy_context("BTCUSDT")
    decisions = LLMDecisionStore(engine.session_factory)
    plans = TradePlanService(engine.session_factory)
    _, signal = await _fresh_entry_signal(engine, decisions, plans, "queued-chief-" + path)
    status = await engine.lease_manager.status(engine.lease_key)
    monkeypatch.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
    try:
        if path == "chief":
            with pytest.raises(LeaseNotHeld):
                await engine.process_signal(signal)
        else:
            state = make_state(database)
            state.engine = engine
            body = ({"client_order_id": "expired-manual", "symbol": "BTCUSDT",
                     "side": "BUY", "quantity": "1", "price": "101"}
                    if path == "manual" else
                    {"side": "LONG", "quantity": "1", "price": "101", "leverage": "3"})
            endpoint = "/manual-orders" if path == "manual" else "/paper/perpetual/open"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(state)),
                                        base_url="http://isolated") as client:
                response = await client.post(endpoint, json=body)
            assert response.status_code == 409
        assert await engine.order_manager.list_all() == []
        assert engine.adapter.orders == {}
        assert await engine.adapter.get_positions() == []
        with pytest.raises(LeaseNotHeld, match="fresh startup safety revalidation"):
            await engine.start("must-not-reuse-old-running-authority")
    finally:
        await engine.stop()


async def test_renewal_expiry_between_query_and_sql_execution_cannot_resurrect(
    database, monkeypatch
):
    manager = LeaseManager(database.session_factory)
    lease = await manager.acquire("delayed-renewal", "writer-a", 10)
    status = await manager.status(lease.lease_key)

    def expire_before_execution(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("UPDATE runtime_leases"):
            monkeypatch.setattr("crypto_trader.runtime.lease._epoch",
                                lambda: status["expires_at"] + 1)

    event.listen(database.engine.sync_engine, "before_cursor_execute", expire_before_execution)
    try:
        assert await manager.renew(
            lease.lease_key, lease.token, 10,
            owner_id=lease.owner_id, fence_generation=lease.fence_generation,
        ) is False
        assert (await manager.status(lease.lease_key))["expires_at"] == status["expires_at"]
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", expire_before_execution)


async def test_direct_perpetual_api_expiry_during_write_rolls_back(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("perpetual-api-fence")
    state = make_state(database)
    state.engine = engine
    status = await engine.lease_manager.status(engine.lease_key)
    before = await engine.ledger.list_entries_recent(limit=200)

    def expire_during_write(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("INSERT INTO ledger_transactions "):
            monkeypatch.setattr("crypto_trader.runtime.lease._epoch",
                                lambda: status["expires_at"] + 1)

    event.listen(database.engine.sync_engine, "after_cursor_execute", expire_during_write)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(state)),
                                    base_url="http://isolated") as client:
            response = await client.post("/paper/perpetual/open", json={
                "side": "LONG", "quantity": "1", "price": "100", "leverage": "3",
            })
        assert response.status_code == 409
        assert {row.entry_id for row in await engine.ledger.list_entries_recent(limit=200)} == {
            row.entry_id for row in before
        }
    finally:
        event.remove(database.engine.sync_engine, "after_cursor_execute", expire_during_write)
        await engine.stop()


@pytest.mark.parametrize("last_write", ["orders", "order_events"])
async def test_expiry_after_order_flush_rolls_back_entire_transaction(
    database, monkeypatch, last_write
):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("expires-during-write")
    status = await engine.lease_manager.status(engine.lease_key)

    def expire_after_insert(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("INSERT INTO " + last_write + " "):
            monkeypatch.setattr("crypto_trader.runtime.lease._epoch",
                                lambda: status["expires_at"] + 1)

    event.listen(database.engine.sync_engine, "after_cursor_execute", expire_after_insert)
    try:
        with pytest.raises(LeaseNotHeld):
            await engine.order_manager.create_from_intent(
                make_intent("expires-after-flush"), trading_mode=TradingMode.PAPER,
            )
        assert await engine.order_manager.list_all() == []
    finally:
        event.remove(database.engine.sync_engine, "after_cursor_execute", expire_after_insert)
        await engine.stop()


async def test_new_owner_cannot_be_borrowed_by_old_engine_services(database, monkeypatch):
    first = make_paper_engine(database, engine_tick_seconds=3600)
    await first.start("writer-a")
    status = await first.lease_manager.status(first.lease_key)
    monkeypatch.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
    second = make_paper_engine(database, engine_tick_seconds=3600)
    try:
        await second.start("writer-b")
        with pytest.raises(LeaseNotHeld):
            await first.order_manager.create_from_intent(
                make_intent("old-writer"), trading_mode=TradingMode.PAPER,
            )
        current = await second.order_manager.create_from_intent(
            make_intent("current-writer"), trading_mode=TradingMode.PAPER,
        )
        assert current.client_order_id == "current-writer"
        assert [order.client_order_id for order in await first.order_manager.list_all()] == [
            "current-writer"
        ]
    finally:
        await first.stop()
        await second.stop()


async def test_lease_expiry_after_durable_begin_blocks_native_account_mutation(
    database, monkeypatch
):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("native-final-boundary")
    engine.adapter.seed_book("BTCUSDT")  # Isolated market fixture, never runtime evidence.
    intent = make_intent("native-expiry")
    intent.price = "101"
    order = await engine.order_manager.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    status = await engine.lease_manager.status(engine.lease_key)
    balances_before = {b.currency: b.total for b in await engine.adapter.get_balances()}

    def arm_begin(session, _context, _instances):
        if any(isinstance(row, AuditEventORM) and row.action == "SETTLEMENT_EXTERNAL_BEGIN"
               for row in session.new):
            session.info["expire_after_durable_begin"] = True

    def expire_after_commit(session):
        if session.info.pop("expire_after_durable_begin", False):
            monkeypatch.setattr("crypto_trader.runtime.lease._epoch",
                                lambda: status["expires_at"] + 1)

    event.listen(Session, "before_flush", arm_begin)
    event.listen(Session, "after_commit", expire_after_commit)
    try:
        with pytest.raises(OrderRejected, match="EXECUTION_LEASE_NOT_HELD"):
            await engine.adapter.submit_order(order)
        assert await engine.adapter.get_positions() == []
        assert {b.currency: b.total for b in await engine.adapter.get_balances()} == balances_before
        assert not any(e.event_type.value == "ORDER_FILLED" for e in engine.adapter.event_log)
        assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
    finally:
        event.remove(Session, "before_flush", arm_begin)
        event.remove(Session, "after_commit", expire_after_commit)
        await engine.stop()
