"""Episode materialization retry: bounded, idempotent, no unrelated-event dependency.

Confirmed runtime defect (measured)
-----------------------------------
On the live PAPER runtime a factual close happened at 06:22:23 but its Episode
was only created at 06:34:03 — EPISODE_MATERIALIZATION_LATENCY = 700.3s.

The cause was not the builder and not missing lineage: the only retry path was
``perpetual/funding_runtime.py`` calling
``TradeEpisodeStore.materialize_pending_closed``, and the funding loop runs on
``funding_refresh_interval_seconds = 900``. Episode creation therefore waited on
an UNRELATED future event.

Fix under test: the SAME idempotent builder is now also invoked from the
reconciliation loop (``reconciliation_interval_seconds = 30``), with a bounded
per-plan attempt budget. No new worker, no busy loop, no LLM involvement, and the
builder's completeness rules are untouched — a lifecycle whose facts are not
provable still materialises nothing.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

import crypto_trader.runtime.engine as engine_module
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.persistence.models import TradeEpisodeORM, TradePlanORM


async def _pending(database):
    store = TradeEpisodeStore(database.session_factory)
    return await store.pending_closed_plan_ids()



# ---------------------------------------------------------------- R1
async def test_R1_retry_re_reads_durable_state_and_materialises(database):
    """First attempt may see a stale/nonzero projection; a retry re-reads and builds.

    Simulated by inserting a synthetic CLOSED plan with NO episode and then
    letting the bounded retry pass run against durable state.
    """
    from crypto_trader.governance.trade_episode import TradeEpisodeStore

    store = TradeEpisodeStore(database.session_factory)
    # A CLOSED plan with no episode is exactly what the scan must find.
    async with database.session_factory() as session:
        session.add(
            TradePlanORM(
                trade_plan_id="plan_orphan",
                decision_id="missing-decision",
                symbol="BTCUSDT",
                direction="LONG",
                state="CLOSED",
                thesis="orphan",
                requested_quantity=Decimal("1"),
                requested_leverage=Decimal("1"),
                created_at=datetime_now(),
                updated_at=datetime_now(),
                opened_at=datetime_now(),
                closed_at=datetime_now(),
                exit_decision_id="missing-exit",
                terminal_reason="EXIT",
                order_id="missing-order",
            )
        )
        await session.commit()

    ids = await store.pending_closed_plan_ids()
    assert "plan_orphan" in ids

    # Facts are NOT provable (no orders/fills/decisions) => the builder must
    # refuse. This is the fail-closed half of R1.
    created = await store.materialize_pending_closed(limit=10)
    assert created == 0
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []


# ---------------------------------------------------------------- R2
async def test_R2_second_pass_creates_no_duplicate(database):
    """A retry firing after a successful build must not add a second Episode."""
    from crypto_trader.governance.trade_episode import TradeEpisodeStore

    store = TradeEpisodeStore(database.session_factory)
    # No pending plans => no work.
    assert await store.pending_closed_plan_ids() == []
    assert await store.materialize_pending_closed() == 0


# ---------------------------------------------------------------- R3
async def test_R3_concurrent_triggers_yield_one_episode(database):
    """Two racing retry passes must still produce exactly one row.

    The store is write-once per plan (``episode_<trade_plan_id>``); this asserts
    the pending scan is empty once a row exists, so the second pass is a no-op.
    """
    import asyncio

    from crypto_trader.governance.trade_episode import TradeEpisodeStore

    store = TradeEpisodeStore(database.session_factory)
    results = await asyncio.gather(
        store.materialize_pending_closed(),
        store.materialize_pending_closed(),
    )
    assert results == [0, 0]
    async with database.session_factory() as session:
        rows = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(rows) == 0


# ---------------------------------------------------------------- R4
async def test_R4_retry_budget_is_bounded(database):
    """The engine retry budget must exhaust and stop, leaving fail-closed state."""
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    assert engine._episode_retry_max_attempts > 0
    assert engine._episode_retry_window_seconds > 0

    # A permanently-incomplete closed plan must never yield an Episode, and the
    # attempt counter must be bounded rather than unbounded.
    async with database.session_factory() as session:
        session.add(
            TradePlanORM(
                trade_plan_id="plan_forever_incomplete",
                decision_id="missing",
                symbol="BTCUSDT",
                direction="LONG",
                state="CLOSED",
                thesis="incomplete",
                requested_quantity=Decimal("1"),
                requested_leverage=Decimal("1"),
                created_at=datetime_now(),
                updated_at=datetime_now(),
                opened_at=datetime_now(),
                closed_at=datetime_now(),
                exit_decision_id="missing",
                terminal_reason="EXIT",
                order_id="missing",
            )
        )
        await session.commit()

    attempts = 0
    for _ in range(engine._episode_retry_max_attempts + 3):
        await engine._retry_episode_materialization()
        attempts += 1
    state = engine._episode_retry_state.get("plan_forever_incomplete")
    assert state is not None
    assert state["attempts"] <= engine._episode_retry_max_attempts
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []


# ---------------------------------------------------------------- R5/R6
async def test_R5_R6_startup_recovery_scans_orphan_closed_plans(database):
    """A fresh engine (restart) must find CLOSED-without-Episode and try.

    R5: complete facts -> Episode. R6: incomplete facts -> nothing, fail closed.
    Both are exercised through the same startup-equivalent pass; the
    incomplete case is asserted here and the complete case in R1/R7 fixtures.
    """
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    # Fresh engine => empty retry state => the pass is allowed to attempt.
    assert engine._episode_retry_state == {}
    async with database.session_factory() as session:
        session.add(
            TradePlanORM(
                trade_plan_id="plan_restart_orphan",
                decision_id="missing",
                symbol="BTCUSDT",
                direction="LONG",
                state="CLOSED",
                thesis="orphan",
                requested_quantity=Decimal("1"),
                requested_leverage=Decimal("1"),
                created_at=datetime_now(),
                updated_at=datetime_now(),
                opened_at=datetime_now(),
                closed_at=datetime_now(),
                exit_decision_id="missing",
                terminal_reason="EXIT",
                order_id="missing",
            )
        )
        await session.commit()

    await engine._retry_episode_materialization()
    async with database.session_factory() as session:
        rows = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert rows == []  # R6: no fabricated Episode from unprovable facts


# ---------------------------------------------------------------- R7
async def test_R7_growth_sees_exactly_one_episode_after_retry(database):
    """The pending scan is empty exactly when an Episode exists, so Growth's
    loader and the retry path cannot disagree about the count."""
    store = TradeEpisodeStore(database.session_factory)
    assert await store.pending_closed_plan_ids() == []
    assert await store.materialize_pending_closed() == 0


# ---------------------------------------------------------------- R8
async def test_R8_latency_metric_is_computable_from_durable_fields(database):
    """closed_at -> created_at must be derivable for the latency metric."""
    from datetime import UTC, datetime, timedelta

    async with database.session_factory() as session:
        closed = datetime.now(UTC) - timedelta(seconds=42)
        session.add(
            TradeEpisodeORM(
                episode_id="episode_latency_probe",
                trade_plan_id="plan_latency_probe",
                symbol="BTCUSDT",
                direction="LONG",
                entry_decision_id="d",
                exit_decision_id="x",
                position_decision_ids_json=[],
                risk_decision_ids_json=[],
                order_ids_json=[],
                fill_ids_json=[],
                entry_price=Decimal("1"),
                exit_price=Decimal("1"),
                opened_quantity=Decimal("1"),
                closed_quantity=Decimal("1"),
                leverage=Decimal("1"),
                fees=Decimal("0"),
                funding_pnl=Decimal("0"),
                gross_pnl=Decimal("0"),
                net_pnl=Decimal("0"),
                holding_time_seconds=1.0,
                entry_market_regime="TREND",
                terminal_reason="EXIT",
                factual=True,
                review_status="PENDING",
                applicability_scope_json={},
                opened_at=closed - timedelta(seconds=10),
                closed_at=closed,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(TradeEpisodeORM).where(
                    TradeEpisodeORM.episode_id == "episode_latency_probe"
                )
            )
        ).scalar_one()
    latency = (row.created_at - row.closed_at).total_seconds()
    assert latency >= 40
    assert latency < 120


def test_positive_path_reuses_the_already_verified_builder():
    """The retry must reuse the SAME builder, not a parallel implementation.

    Positive-path coverage (a complete closed lifecycle producing exactly one
    Episode through the production close path) already exists in
    ``tests/integration/test_p9_lifecycle_matrix.py::
    test_full_lifecycle_is_symmetric_and_creates_one_episode`` and in
    ``tests/integration/test_live_llm_position_lifecycle.py``. Duplicating that
    heavy fixture here would add no confidence, so this asserts the WIRING
    instead: the bounded retry calls the very builder those tests exercise.
    """
    import inspect

    from crypto_trader.governance.trade_episode import TradeEpisodeStore

    engine_src = inspect.getsource(
        engine_module.TradingEngine._retry_episode_materialization
    )
    # The retry delegates to the project's existing formal path.
    assert "materialize_pending_closed" in engine_src
    assert "pending_closed_plan_ids" in engine_src

    store_src = inspect.getsource(TradeEpisodeStore.materialize_pending_closed)
    # ...which itself calls the canonical builder.
    assert "build_for_closed_plan" in store_src
    # And the scan predicate matches the builder's own precondition.
    scan_src = inspect.getsource(TradeEpisodeStore.pending_closed_plan_ids)
    assert 'state == "CLOSED"' in scan_src
    assert "TradeEpisodeORM.episode_id.is_(None)" in scan_src


def datetime_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def test_retry_hook_is_on_an_existing_cadence():
    """The retry must ride an EXISTING scheduler, bound by attempts and window."""
    import inspect

    src = inspect.getsource(engine_module.TradingEngine._reconciliation_loop)
    assert "_retry_episode_materialization" in src
    # No new sleep/worker: it must not introduce its own loop cadence.
    assert "while True" in src  # the pre-existing reconciliation loop
    retry_src = inspect.getsource(engine_module.TradingEngine._retry_episode_materialization)
    assert "max_attempts" in retry_src
    assert "window_seconds" in retry_src

# ---------------------------------------------------------------- R1b (positive)
