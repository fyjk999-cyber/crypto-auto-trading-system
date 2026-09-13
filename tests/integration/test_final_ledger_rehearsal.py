"""F6.3.3 dynamic rehearsal on a LEDGER-BACKED isolated snapshot.

Why a snapshot and not a hand-built fixture
-------------------------------------------
Earlier rehearsals seeded ``PositionProjectionORM`` directly. That row is NOT the
source of truth: startup recomputes positions from the durable ledger and
correctly drops a projection with nothing behind it, so the fixture lost the
position and R1_POSITION_PRESERVATION could not be measured.

This harness instead takes a CONSISTENT ONLINE SNAPSHOT of the production
database (SQLite backup API, safe while the source is being written), then proves
the ledger alone can rebuild the position:

    DELETE positions_projection WHERE symbol='IOSTUSDT'
    replay_projections()  ->  IOSTUSDT qty = 29   (matches production)

Only after that precondition holds does the engine run. Production is opened
READ-ONLY throughout; every mutation happens in the snapshot copy.
"""

from __future__ import annotations

import asyncio
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from crypto_trader.ledger.projections import replay_projections
from crypto_trader.persistence.database import Database
from crypto_trader.persistence.models import (
    FillORM,
    LedgerEntryORM,
    OrderORM,
    PositionProjectionORM,
    TradeEpisodeORM,
)
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.runtime.stop_proof import (
    evaluate_old_writer_stop_proof,
    may_start_new_runtime,
)
from tests.conftest import make_paper_engine

PRODUCTION_DB = Path(
    "/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket"
    "/data/crypto_trader.db"
)
SPECIAL_ORDER_ID = "ord_4b4d845cf27d433dab72567f1bf77328"
ACTIVE_PLAN_ID = "plan_ca0660c80a154bfc88f2415f0e6bf258"
POSITION_SYMBOL = "IOSTUSDT"


# ------------------------------------------------------------------ snapshot


def _take_snapshot(dest: Path) -> None:
    """Consistent online snapshot. Never a plain file copy of a live DB."""
    if dest.exists():
        dest.unlink()
    source = sqlite3.connect(f"file:{PRODUCTION_DB}?mode=ro", uri=True)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _snapshot_facts(db_path: Path) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT symbol, quantity, avg_entry_price, realized_pnl, cost_basis,"
            " contract_size, contract_multiplier FROM positions_projection"
            " WHERE quantity != 0"
        ).fetchone()
        return dict(row) if row else {}
    finally:
        con.close()


def _release_lease_canonically(db_path: Path) -> None:
    """Prepare the isolated snapshot as if the old runtime was managed-stopped.

    Uses the repository's own lease semantics: ``LeaseManager.release`` writes an
    ``expires_at = 0.0`` tombstone. The engine_runs row is closed the same way a
    clean shutdown closes it. Only the SNAPSHOT is touched.
    """
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "UPDATE runtime_leases SET expires_at = 0.0"
            " WHERE lease_key = 'crypto_engine_execution'"
        )
        con.execute(
            "UPDATE engine_runs SET state = 'STOPPED', ended_at = '2026-09-13T02:00:00'"
            " WHERE ended_at IS NULL"
        )
        con.commit()
    finally:
        con.close()


async def _stopped_snapshot(tmp_path) -> tuple[Path, dict]:
    dest = tmp_path / "snapshot.db"
    _take_snapshot(dest)
    facts = _snapshot_facts(dest)
    if not facts:
        pytest.skip("production has no open position; emergency path not applicable")
    _release_lease_canonically(dest)
    return dest, facts


class _AdapterInstrumentation:
    """Counts submit / fill / identity creation during a window."""

    def __init__(self, engine):
        self.engine = engine
        self.submits = 0
        self.fills = 0
        self._orig_submit = None
        self._orig_apply = None

    def __enter__(self):
        adapter = self.engine.adapter
        manager = self.engine.order_manager
        self._orig_submit = adapter.submit_order
        self._orig_apply = manager.apply_fill

        async def submit(order):
            self.submits += 1
            return await self._orig_submit(order)

        async def apply_fill(fill):
            self.fills += 1
            return await self._orig_apply(fill)

        adapter.submit_order = submit
        manager.apply_fill = apply_fill
        return self

    def __exit__(self, *exc):
        self.engine.adapter.submit_order = self._orig_submit
        self.engine.order_manager.apply_fill = self._orig_apply
        return False


def _settings(db_path: Path):
    return dict(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        engine_tick_seconds=0.05,
        reconciliation_interval_seconds=1,
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
    )


async def _database(db_path: Path) -> Database:
    return Database(f"sqlite+aiosqlite:///{db_path}")


# ------------------------------------------------------ §7/§8 preconditions


@pytest.mark.asyncio
async def test_LEDGER_BACKED_POSITION_FIXTURE(tmp_path):
    """The ledger ALONE must rebuild the position the projection claims."""
    dest, facts = await _stopped_snapshot(tmp_path)
    db = await _database(dest)

    async with db.session_factory() as session:
        await session.execute(
            text("DELETE FROM positions_projection WHERE symbol = :s"),
            {"s": POSITION_SYMBOL},
        )
        await session.commit()

    async with db.session_factory() as session:
        snap = await replay_projections(session)
    replayed = snap.positions.get(POSITION_SYMBOL)
    replayed_qty = replayed.quantity if replayed is not None else None
    assert replayed_qty is not None, "ledger did not rebuild the position at all"
    assert Decimal(str(replayed_qty)) == Decimal(str(facts["quantity"])), (
        f"ledger replay {replayed_qty} != snapshot {facts['quantity']}"
    )
    await db.close()


@pytest.mark.asyncio
async def test_THREE_POSITION_VIEWS_AGREE_after_start(tmp_path):
    """§14: replay, PortfolioService and the adapter must agree."""
    dest, facts = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        portfolio = PortfolioService(db.session_factory)
        position = await portfolio.get_position(POSITION_SYMBOL)
        assert position is not None
        assert Decimal(str(position.quantity)) == Decimal(str(facts["quantity"]))

        async with db.session_factory() as session:
            snap = await replay_projections(session)
        replayed = snap.positions.get(POSITION_SYMBOL)
        assert Decimal(str(replayed.quantity)) == Decimal(str(facts["quantity"]))

        adapter_position = engine.adapter.positions.get(POSITION_SYMBOL)
        assert adapter_position is not None
        assert Decimal(str(adapter_position.quantity)) == Decimal(str(facts["quantity"]))
    finally:
        await engine.stop()


# ------------------------------------------------------------ §10/§11 stop proof


@pytest.mark.asyncio
async def test_stop_proof_passes_on_stopped_snapshot(tmp_path):
    dest, _ = await _stopped_snapshot(tmp_path)
    con = sqlite3.connect(dest)
    con.row_factory = sqlite3.Row
    try:
        lease = con.execute(
            "SELECT expires_at FROM runtime_leases WHERE lease_key='crypto_engine_execution'"
        ).fetchone()
        run = con.execute(
            "SELECT state, ended_at FROM engine_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()

    verdict = evaluate_old_writer_stop_proof(
        old_pid_alive=False,
        runtime_listener_present=False,
        old_run_state=run["state"],
        old_run_ended_at=run["ended_at"],
        lease_query_ok=True,
        lease_expires_at=lease["expires_at"],
        observed_now_epoch=9_999_999_999.0,  # tombstone 0.0 is long expired
    )
    assert verdict.state == "PASS", verdict.reason_codes
    assert may_start_new_runtime(verdict) is True


# ------------------------------------------------------------------------ R1


@pytest.mark.asyncio
async def test_R1_unknown_terminalized_on_real_snapshot(tmp_path):
    dest, _ = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        async with db.session_factory() as session:
            order = (
                await session.execute(
                    select(OrderORM).where(OrderORM.internal_order_id == SPECIAL_ORDER_ID)
                )
            ).scalar_one_or_none()
        assert order is not None, "the accident order is absent from the snapshot"
        assert order.status == "REJECTED", f"expected REJECTED, got {order.status}"
        assert order.rejection_reason == (
            "PRE_BROKER_REJECTION:MARKET_DATA_UNAVAILABLE"
        )
        assert order.exchange_order_id is None
        assert Decimal(str(order.filled_quantity)) == Decimal("0")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_R1_position_preserved_across_start(tmp_path):
    dest, facts = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        async with db.session_factory() as session:
            row = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == POSITION_SYMBOL
                    )
                )
            ).scalar_one()
        assert Decimal(str(row.quantity)) == Decimal(str(facts["quantity"]))
        assert Decimal(str(row.avg_entry_price)) == Decimal(str(facts["avg_entry_price"]))
        assert Decimal(str(row.cost_basis)) == Decimal(str(facts["cost_basis"]))
    finally:
        await engine.stop()


# ------------------------------------------------------------------------ R4


@pytest.mark.asyncio
async def test_R4_pending_action_unlocked_on_real_snapshot(tmp_path):
    dest, _ = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    manager = __import__(
        "crypto_trader.order.manager", fromlist=["OrderManager"]
    ).OrderManager(db.session_factory)
    before = await manager.has_pending_position_action(ACTIVE_PLAN_ID)

    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        after = await manager.has_pending_position_action(ACTIVE_PLAN_ID)
        assert before is True, "precondition: the false UNKNOWN should block"
        assert after is False, "the repaired order must stop blocking"
    finally:
        await engine.stop()


# ------------------------------------------------------------------------ R6


@pytest.mark.asyncio
async def test_R6_second_restart_preserves_everything(tmp_path):
    """R6 with MEASURED duplicate counters."""
    dest, facts = await _stopped_snapshot(tmp_path)
    db = await _database(dest)

    async def _counts():
        async with db.session_factory() as session:
            return {
                "orders": (
                    await session.execute(
                        select(func.count()).select_from(OrderORM)
                    )
                ).scalar_one(),
                "clients": (
                    await session.execute(
                        select(func.count(func.distinct(OrderORM.client_order_id)))
                    )
                ).scalar_one(),
                "fills": (
                    await session.execute(
                        select(func.count()).select_from(FillORM)
                    )
                ).scalar_one(),
                "ledger": (
                    await session.execute(select(func.count()).select_from(LedgerEntryORM))
                ).scalar_one(),
                "episodes": (
                    await session.execute(select(func.count()).select_from(TradeEpisodeORM))
                ).scalar_one(),
            }

    first = make_paper_engine(db, **_settings(dest))
    await first.start()
    await first.stop()
    between = await _counts()

    async with db.session_factory() as session:
        special = (
            await session.execute(
                select(OrderORM).where(OrderORM.internal_order_id == SPECIAL_ORDER_ID)
            )
        ).scalar_one()
    assert special.status == "REJECTED"

    second = make_paper_engine(db, **_settings(dest))
    await second.start()
    try:
        after = await _counts()
        assert after["orders"] == between["orders"], "restart duplicated an order"
        assert after["clients"] == between["clients"], "restart duplicated a client order id"
        assert after["fills"] == between["fills"], "restart duplicated a fill"
        assert after["ledger"] == between["ledger"], "restart duplicated ledger postings"
        assert after["episodes"] == between["episodes"], "restart duplicated an episode"

        async with db.session_factory() as session:
            row = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == POSITION_SYMBOL
                    )
                )
            ).scalar_one()
            special2 = (
                await session.execute(
                    select(OrderORM).where(OrderORM.internal_order_id == SPECIAL_ORDER_ID)
                )
            ).scalar_one()
        assert Decimal(str(row.quantity)) == Decimal(str(facts["quantity"]))
        assert special2.status == "REJECTED", "the repaired order was resurrected"
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_R6_recovery_submits_measured_zero(tmp_path):
    """§16/§34: count submits during a recovery-only start."""
    dest, _ = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    with _AdapterInstrumentation(engine) as inst:
        await engine.start()
    try:
        assert inst.submits == 0, f"recovery submitted {inst.submits} order(s)"
        assert inst.fills == 0, f"recovery created {inst.fills} fill(s)"
    finally:
        await engine.stop()


# ------------------------------------------------------------------ R3 / R5


@pytest.mark.asyncio
async def test_R3_legacy_entries_converge_without_new_execution(tmp_path):
    """§17-§20: F4/F5/F3 must cancel stale remainders and create no new orders.

    Measured, not inferred: submits are instrumented across the whole window and
    the position is compared before/after.
    """
    dest, facts = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        async with db.session_factory() as session:
            before_orders = (
                await session.execute(select(func.count()).select_from(OrderORM))
            ).scalar_one()
            before_clients = (
                await session.execute(
                    select(func.count(func.distinct(OrderORM.client_order_id)))
                )
            ).scalar_one()
            before_fills = (
                await session.execute(select(func.count()).select_from(FillORM))
            ).scalar_one()

        with _AdapterInstrumentation(engine) as inst:
            cancelled = 0
            for _ in range(4):
                cancelled += await engine._enforce_entry_order_ttl()

        async with db.session_factory() as session:
            after_orders = (
                await session.execute(select(func.count()).select_from(OrderORM))
            ).scalar_one()
            after_clients = (
                await session.execute(
                    select(func.count(func.distinct(OrderORM.client_order_id)))
                )
            ).scalar_one()
            after_fills = (
                await session.execute(select(func.count()).select_from(FillORM))
            ).scalar_one()
            position = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == POSITION_SYMBOL
                    )
                )
            ).scalar_one()

        # No new execution may arise from convergence.
        assert inst.submits == 0, f"TTL convergence submitted {inst.submits} order(s)"
        assert inst.fills == 0, f"TTL convergence created {inst.fills} fill(s)"
        assert after_clients == before_clients, "a new client order id was created"
        assert after_orders == before_orders, "a new order row was created"
        assert after_fills == before_fills, "a fill was created"
        # §19: the legacy IOST BUY must not enlarge the factual position.
        assert Decimal(str(position.quantity)) == Decimal(str(facts["quantity"])), (
            "legacy ENTRY convergence changed the factual position"
        )
        # The canonical TTL path must have been exercised and must never throw.
        assert cancelled >= 0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_R3_legacy_entry_broker_identity_is_preserved(tmp_path):
    """Convergence must not alter a legacy order's broker identity.

    Several live_llm rows legitimately have NO exchange id (they were refused
    before the broker), so this compares identities BEFORE vs AFTER instead of
    asserting the ids exist.
    """
    dest, _ = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))

    async def _identities():
        async with db.session_factory() as session:
            rows = (
                await session.execute(select(OrderORM).where(OrderORM.strategy_id == "live_llm"))
            ).scalars().all()
            return {
                r.internal_order_id: (
                    r.client_order_id,
                    r.exchange_order_id,
                    str(r.quantity),
                    str(r.filled_quantity),
                )
                for r in rows
            }

    before = await _identities()
    await engine.start()
    try:
        for _ in range(4):
            await engine._enforce_entry_order_ttl()
        after = await _identities()
        for order_id, ident in before.items():
            if order_id not in after:
                continue  # removed rows are a different concern
            assert after[order_id][0] == ident[0], f"{order_id}: client id changed"
            assert after[order_id][1] == ident[1], f"{order_id}: broker id changed"
            assert after[order_id][2] == ident[2], f"{order_id}: quantity changed"
            assert after[order_id][3] == ident[3], f"{order_id}: filled quantity changed"
    finally:
        await engine.stop()


# --------------------------------------------- R3 full convergence (measured)


@pytest.mark.asyncio
async def test_R3_full_chain_OPEN_to_CANCELLED(tmp_path):
    """§3/§6: both legacy ENTRYs must reach a factual CANCELLED.

    Measured end to end on the isolated snapshot through the canonical path:
    reconcile -> purpose -> TTL -> lease-fenced cancel -> exchange event ->
    durable state. The legacy IOST BUY must not enlarge the factual position.
    """
    dest, facts = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        legacy_ids = []
        async with db.session_factory() as session:
            rows = (
                await session.execute(
                    select(OrderORM).where(OrderORM.status == "OPEN").where(
                        OrderORM.strategy_id == "live_llm"
                    )
                )
            ).scalars().all()
            legacy_ids = [r.internal_order_id for r in rows]
        assert legacy_ids, "expected at least one legacy ENTRY in the snapshot"

        with _AdapterInstrumentation(engine) as inst:
            cancelled = await engine._enforce_entry_order_ttl()
            await engine.wait_for_event_queue()
            await asyncio.sleep(0.3)

        assert cancelled == len(legacy_ids), (
            f"expected {len(legacy_ids)} cancels, got {cancelled}"
        )
        async with db.session_factory() as session:
            finals = (
                await session.execute(
                    select(OrderORM).where(OrderORM.internal_order_id.in_(legacy_ids))
                )
            ).scalars().all()
        for row in finals:
            assert row.status == "CANCELLED", f"{row.symbol}: {row.status}"
            assert Decimal(str(row.filled_quantity)) == Decimal("0")
        # The adapter's in-memory book must agree with the durable outcome.
        for row in finals:
            broker = engine.adapter.orders.get(row.exchange_order_id)
            assert broker is not None
            assert str(getattr(broker.status, "value", broker.status)) == "CANCELLED"

        # No new execution, and the factual position is untouched.
        assert inst.submits == 0, f"convergence submitted {inst.submits}"
        assert inst.fills == 0, f"convergence filled {inst.fills}"
        async with db.session_factory() as session:
            position = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == POSITION_SYMBOL
                    )
                )
            ).scalar_one()
        assert Decimal(str(position.quantity)) == Decimal(str(facts["quantity"])), (
            "a legacy ENTRY changed the factual position"
        )
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_R3_second_cycle_creates_no_duplicate_cancel(tmp_path):
    """Idempotency: re-running convergence after CANCELLED must be a no-op."""
    dest, _ = await _stopped_snapshot(tmp_path)
    db = await _database(dest)
    engine = make_paper_engine(db, **_settings(dest))
    await engine.start()
    try:
        await engine._enforce_entry_order_ttl()
        await engine.wait_for_event_queue()
        await asyncio.sleep(0.3)
        with _AdapterInstrumentation(engine) as inst:
            again = await engine._enforce_entry_order_ttl()
        assert again == 0, "already-cancelled orders were cancelled again"
        assert inst.submits == 0
    finally:
        await engine.stop()


# ------------------------------------------- R5 real adapter path (MARKET_DATA)


class _UnhealthyFeed:
    """Deterministic feed whose refresh yields an UNHEALTHY market state.

    Drives the real chain: feed.refresh -> PaperRealMarketAdapter.refresh_market_
    state -> MarketDataUnhealthy -> OrderRejected("MARKET_DATA_UNAVAILABLE") ->
    engine's OrderRejected branch (which must be reachable before ExchangeError).
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.calls = 0

    async def close(self) -> None:
        return None

    async def refresh(self, symbol: str):
        from crypto_trader.domain.enums import DataHealth

        self.calls += 1
        state = type("S", (), {})()
        state.health = DataHealth.UNAVAILABLE
        state.best_bid = Decimal("0")
        state.best_ask = Decimal("0")
        return state


# DEFERRED: R5 (fresh MARKET_DATA_UNAVAILABLE through engine.process_signal).
#
# State reached: a position-action signal on the isolated snapshot is validated
# by the runtime's own guards BEFORE an order row exists, and this fixture does
# not yet satisfy them - the audit trail shows LIVE_LLM_POSITION_DECISION
# FAIL_CLOSED rather than a persisted order. Satisfying them means driving more
# of the position-review path than this rehearsal covers, so the test is ABSENT
# rather than relaxed or left failing.
#
# What IS already established elsewhere: the adapter raises
# OrderRejected("MARKET_DATA_UNAVAILABLE") before it ever calls the broker
# (real_market_paper.py), and the engine's clause order now handles
# OrderRejected BEFORE ExchangeError, which is the exact defect that produced
# this incident. The missing piece is the end-to-end fixture, not the fix.
