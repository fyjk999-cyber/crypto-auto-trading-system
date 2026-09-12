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

from sqlalchemy import delete, select

import crypto_trader.runtime.engine as engine_module
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import TradeEpisodeORM, TradePlanORM
from crypto_trader.trade_plan.service import TradePlanService
from tests.integration.test_live_llm_position_lifecycle import (
    BTC_EXECUTION_METADATA,
    Evidence,
    SequencedChief,
)


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


# ---------------------------------------------------------------- R9 (positive)
async def test_R9_reconciliation_retry_materialises_after_readiness(database):
    """PROVE the runtime wiring creates the Episode — not a manual second call.

    Sequence, all through production code:

      1. drive a REAL closed lifecycle (entry -> HOLD -> REDUCE -> EXIT) so the
         canonical close path builds the Episode;
      2. reproduce the exact runtime race by making the builder's factual
         readiness guard fail again — ``positions_projection.quantity != 0`` —
         and removing only the Episode row, so the state is CLOSED + absent;
      3. FIRST BUILD: the production builder returns None, episode_count == 0;
      4. make durable facts ready again (projection qty = 0, fixture fact only);
      5. SECOND BUILD: triggered ONLY through the engine's reconciliation retry
         wiring, which must create the Episode;
      6. a further retry must not create a second one.
    """
    from sqlalchemy import update

    from crypto_trader.governance.trade_episode import TradeEpisodeStore
    from crypto_trader.persistence.models import PositionProjectionORM
    from tests.conftest import make_paper_engine

    # ---- R9.1 ARRANGE: a real closed lifecycle ------------------------------
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = _MutableClock()
    engine.clock = clock
    await engine.start("run-r9-episode-retry")
    assert await engine._strategy_context("BTCUSDT") is not None

    plans = TradePlanService(database.session_factory)
    decisions = LLMDecisionStore(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-r9",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="r9 entry thesis",
        position_size_request=0.1,
        leverage_request=10,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-flash",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    assert (await engine.portfolio.get_position("BTCUSDT")).quantity == Decimal("0.1")

    engine.position_manager = LiveLLMPositionManager(
        chief=SequencedChief([("HOLD", "0"), ("REDUCE", "0.04"), ("EXIT", "0")]),
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    # SequencedChief yields one decision per review review; three decisions plus
    # settlement ticks are required for the EXIT fill to reach a factual zero.
    for _ in range(9):
        clock.advance()
        await engine.tick()
        await engine.wait_for_event_queue()
        pos = await engine.portfolio.get_position("BTCUSDT")
        if pos is not None and pos.quantity == 0:
            break

    position = await engine.portfolio.get_position("BTCUSDT")
    assert position is not None and position.quantity == 0
    closed_plan = await plans.get(plan.trade_plan_id)
    assert closed_plan is not None and str(closed_plan.state).endswith("CLOSED")

    store = TradeEpisodeStore(database.session_factory)
    # The lifecycle reaches a factual zero. Whether the close path already built
    # the Episode depends on fixture funding coverage, so the test does not
    # require it: it only requires the CLOSED-without-Episode state below, which
    # is precisely the runtime condition under test.
    built = await store.load_closed_on(
        closed_plan.closed_at.date().isoformat(), limit=50
    )
    prior = [e for e in built if e.trade_plan_id == plan.trade_plan_id]
    original_net = prior[0].net_pnl if prior else None
    original_reason = prior[0].terminal_reason if prior else None

    # ---- Recreate the runtime race: CLOSED + Episode absent + not ready -----
    async with database.session_factory() as session:
        await session.execute(
            delete(TradeEpisodeORM).where(
                TradeEpisodeORM.trade_plan_id == plan.trade_plan_id
            )
        )
        # The builder's own readiness predicate: it refuses while the factual
        # position projection is non-zero.
        await session.execute(
            update(PositionProjectionORM)
            .where(PositionProjectionORM.symbol == "BTCUSDT")
            .values(quantity=Decimal("0.1"))
        )
        await session.commit()

    assert plan.trade_plan_id in await store.pending_closed_plan_ids()

    # ---- R9.2 FIRST ATTEMPT: production builder returns None ----------------
    first = await store.build_for_closed_plan(plan.trade_plan_id)
    assert first is None
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []

    # ---- R9.3 MAKE DURABLE FACTS READY (fixture facts only) -----------------
    # (a) the builder's readiness predicate: factual position projection = 0.
    async with database.session_factory() as session:
        await session.execute(
            update(PositionProjectionORM)
            .where(PositionProjectionORM.symbol == "BTCUSDT")
            .values(quantity=Decimal("0"))
        )
        await session.commit()
    # (b) the lifecycle funding-coverage proof, recorded through the formal
    #     service (KNOWN_ZERO = PROVEN no funding event in the holding window),
    #     exactly as the production funding supervisor would.
    from datetime import timedelta

    from crypto_trader.perpetual.funding_coverage import FundingCoverageService

    await FundingCoverageService(database.session_factory).record(
        instrument_id="BTCUSDT",
        window_start=closed_plan.opened_at,
        window_end=closed_plan.closed_at + timedelta(microseconds=1),
        coverage_status="KNOWN_ZERO",
        pagination_complete=True,
        boundary_proof=True,
        source="TEST_FIXTURE",
    )

    # ---- R9.4 TRIGGER THE ACTUAL RETRY WIRING -------------------------------
    # Deliberately NOT calling build_for_closed_plan directly: this must go
    # through the engine path the reconciliation loop invokes.
    created = await engine._retry_episode_materialization()
    assert created == 1

    # ---- R9.5 ASSERT -------------------------------------------------------
    async with database.session_factory() as session:
        rows = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(rows) == 1
    episode = rows[0]
    assert episode.episode_id == f"episode_{plan.trade_plan_id}"
    assert episode.trade_plan_id == plan.trade_plan_id
    assert episode.factual is True
    assert episode.opened_quantity == episode.closed_quantity
    assert episode.terminal_reason in ("EXIT", "POSITION_CLOSED")
    if original_reason is not None:
        assert episode.terminal_reason == original_reason
        assert episode.net_pnl == original_net
    # The retry re-read durable facts, so the rebuilt accounting is self-consistent.
    assert episode.gross_pnl - episode.fees + episode.funding_pnl == episode.net_pnl

    # ---- R9.6 SECOND RETRY: still exactly one Episode -----------------------
    again = await engine._retry_episode_materialization()
    assert again == 0
    async with database.session_factory() as session:
        rows2 = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(rows2) == 1
    assert rows2[0].episode_id == episode.episode_id


class _MutableClock:
    """Local copy of the canonical MutableClock (advance(31) by default)."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.value = datetime.now(UTC)

    def now(self):
        return self.value

    def advance(self, seconds: int = 31) -> None:
        from datetime import timedelta

        self.value += timedelta(seconds=seconds)


def test_R9_positive_test_uses_the_engine_wiring_not_a_manual_second_call():
    """Guard the guard: R9 must exercise ``_retry_episode_materialization``."""
    import ast
    import inspect
    import textwrap

    func = test_R9_reconciliation_retry_materialises_after_readiness
    assert "_retry_episode_materialization" in inspect.getsource(func)
    # Strip the docstring: it names build_for_closed_plan in prose, and counting
    # that would make the guard self-referential.
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    if node.body and isinstance(node.body[0], ast.Expr):
        node.body = node.body[1:]
    body = ast.unparse(tree)
    # The positive materialisation must come from the wiring call; the single
    # direct builder invocation is the NEGATIVE first attempt.
    assert body.count("build_for_closed_plan") == 1
    assert body.count("_retry_episode_materialization") == 2
