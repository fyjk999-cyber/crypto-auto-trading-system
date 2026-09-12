"""trade_episode health must observe durable facts, not a close-time snapshot.

Confirmed runtime defect
------------------------
On the live PAPER runtime (build 460553f2) BEATUSDT closed at 07:46:57 with the
Episode not yet materialised. ``runtime/engine.py`` set::

    self.health.set("trade_episode", False, "closed lifecycle lacks factual lineage")

The Episode then materialised legitimately at 08:00:19 (latency 802.2s), but the
component stayed False forever: the close path is the ONLY write site, and it
never re-reads durable state. Evidence of staleness: the component's
``checked_at`` (07:46:57.668) predates the Episode row (08:00:19.813).

This is CONTROL-PLANE HEALTH STALENESS — not a trading, accounting or Episode
defect. The fix adds a fact-driven refresh on the existing reconciliation
cadence; health observes facts and never creates or mutates them.

Aggregation is worst-state-wins so one successful Episode cannot mask a failure:

    HEALTHY (none pending) < PENDING (budget left) < FAILED (budget exhausted)
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from crypto_trader.persistence.models import (
    FillORM,
    OrderORM,
    TradeEpisodeORM,
    TradePlanORM,
)
from tests.conftest import make_paper_engine

COMPONENT = "trade_episode"


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def _seed_funding_coverage(database, symbol: str) -> None:
    """Prove funding completeness for the holding window (builder requirement)."""
    from datetime import UTC, datetime

    from crypto_trader.perpetual.funding_coverage import FundingCoverageService

    await FundingCoverageService(database.session_factory).record(
        instrument_id=symbol,
        window_start=datetime(2000, 1, 1, tzinfo=UTC),
        window_end=datetime(2030, 1, 1, tzinfo=UTC),
        coverage_status="KNOWN_ZERO",
        pagination_complete=True,
        boundary_proof=True,
        fetched_count=0,
        window_event_count=0,
    )


async def _add_closed_plan(
    database, plan_id: str, *, symbol: str = "BTCUSDT", complete: bool = True
):
    """Persist a CLOSED plan with a PROVABLE lifecycle.

    ``complete=True`` seeds everything the builder requires (entry order, a
    reduce_only close order carrying the exit decision, matching entry/close
    fills whose quantities are equal, a risk decision id shared by the orders,
    and proven funding coverage) so ``build_for_closed_plan`` can succeed.

    ``complete=False`` omits the lifecycle facts, so the builder must refuse —
    that is the retry-exhaustion half.
    """
    from datetime import timedelta

    from crypto_trader.persistence.models import (
        FillORM,
        LedgerEntryORM,
        LedgerTransactionORM,
        LLMDecisionORM,
        OrderORM,
    )

    now = _now()
    entry_order_id = f"ord_entry_{plan_id}"
    close_order_id = f"ord_close_{plan_id}"
    risk_id = f"risk_{plan_id}"
    exit_decision_id = f"dec_exit_{plan_id}"
    quantity = Decimal("1")

    async with database.session_factory() as session:
        session.add(
            TradePlanORM(
                trade_plan_id=plan_id,
                decision_id=f"dec_entry_{plan_id}",
                symbol=symbol,
                direction="LONG",
                state="CLOSED",
                thesis="test lifecycle",
                requested_quantity=quantity,
                requested_leverage=Decimal("1"),
                risk_decision_id=risk_id if complete else None,
                created_at=now,
                updated_at=now,
                opened_at=now - timedelta(minutes=5),
                closed_at=now,
                exit_decision_id=exit_decision_id if complete else None,
                terminal_reason="EXIT",
                order_id=entry_order_id if complete else None,
            )
        )
        if complete:
            session.add(
                OrderORM(
                    internal_order_id=entry_order_id,
                    client_order_id=f"cid_entry_{plan_id}",
                    exchange_order_id=f"ex_{entry_order_id}",
                    symbol=symbol,
                    side="BUY",
                    order_type="LIMIT",
                    time_in_force="GTC",
                    price=Decimal("100"),
                    quantity=quantity,
                    filled_quantity=quantity,
                    avg_fill_price=Decimal("100"),
                    status="FILLED",
                    trading_mode="PAPER",
                    strategy_id="live_llm",
                    run_id="run_test",
                    created_at=now - timedelta(minutes=5),
                    updated_at=now,
                    metadata_json={
                        "trade_plan_id": plan_id,
                        "risk_decision_id": risk_id,
                        "instrument_type": "SPOT",
                        "quote_currency": "USDT",
                        "contract_size": "1",
                        "contract_multiplier": "1",
                    },
                )
            )
            session.add(
                OrderORM(
                    internal_order_id=close_order_id,
                    client_order_id=f"cid_close_{plan_id}",
                    exchange_order_id=f"ex_{close_order_id}",
                    symbol=symbol,
                    side="SELL",
                    order_type="LIMIT",
                    time_in_force="GTC",
                    price=Decimal("101"),
                    quantity=quantity,
                    filled_quantity=quantity,
                    avg_fill_price=Decimal("101"),
                    status="FILLED",
                    trading_mode="PAPER",
                    strategy_id="live_llm_position",
                    run_id="run_test",
                    created_at=now - timedelta(minutes=1),
                    updated_at=now,
                    metadata_json={
                        "trade_plan_id": plan_id,
                        "risk_decision_id": risk_id,
                        "decision_id": exit_decision_id,
                        "reduce_only": True,
                        "instrument_type": "SPOT",
                        "quote_currency": "USDT",
                        "contract_size": "1",
                        "contract_multiplier": "1",
                    },
                )
            )
            for fill_id, order_id, price in (
                (f"fill_entry_{plan_id}", entry_order_id, "100"),
                (f"fill_close_{plan_id}", close_order_id, "101"),
            ):
                session.add(
                    FillORM(
                        fill_id=fill_id,
                        trade_id=f"trade_{fill_id}",
                        order_id=order_id,
                        client_order_id=f"cid_{fill_id}",
                        exchange_order_id=f"ex_{fill_id}",
                        symbol=symbol,
                        side="BUY" if order_id == entry_order_id else "SELL",
                        price=Decimal(price),
                        quantity=quantity,
                        fee=Decimal("0.01"),
                        fee_currency="USDT",
                        timestamp=now - timedelta(minutes=3),
                        payload_json={},
                    )
                )
            # The builder resolves the entry decision row from plan.decision_id.
            session.add(
                LLMDecisionORM(
                    decision_id=f"dec_entry_{plan_id}",
                    run_id="run_test",
                    symbol=symbol,
                    position_state="FLAT",
                    action="LONG",
                    model_provider="deepseek",
                    model="deepseek-flash",
                    model_version="test",
                    prompt_version="test",
                    market_regime="TREND",
                    created_at=now - timedelta(minutes=6),
                )
            )
            # The builder requires PROVEN ledger ownership for the entry fill:
            # exactly one VERIFIED account|instrument|currency owner.
            session.add(
                LedgerTransactionORM(
                    transaction_id=f"txn_own_{plan_id}",
                    account_id="default",
                    instrument_id=symbol,
                    ownership_status="VERIFIED",
                    entry_type="DEPOSIT",
                    created_at=now - timedelta(minutes=5),
                    fill_id=f"fill_entry_{plan_id}",
                    metadata_json={"amount": str(quantity), "currency": "USDT"},
                )
            )
            session.add(
                LedgerEntryORM(
                    entry_id=f"led_own_{plan_id}",
                    transaction_id=f"txn_own_{plan_id}",
                    seq=1,
                    entry_type="DEPOSIT",
                    account="CASH",
                    direction="DEBIT",
                    amount=str(quantity),
                    currency="USDT",
                    created_at=now - timedelta(minutes=5),
                    fill_id=f"fill_entry_{plan_id}",
                    metadata_json={},
                )
            )
        await session.commit()

    if complete:
        await _seed_funding_coverage(database, symbol)


async def _count(database, model) -> int:
    async with database.session_factory() as session:
        return int(
            (await session.execute(select(func.count()).select_from(model))).scalar_one()
        )


async def _add_episode_directly(database, plan_id: str) -> None:
    """Materialise through the durable store's formal path (never by hand)."""
    from crypto_trader.governance.trade_episode import TradeEpisodeStore

    store = TradeEpisodeStore(database.session_factory)
    await store.build_for_closed_plan(plan_id)


# ------------------------------------------------------------------ H1
async def test_H1_initial_missing_reports_pending_not_corrupt(database):
    """H1: closed plan, Episode absent, retry budget intact -> PENDING detail."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h1")

    outcome = await engine._refresh_trade_episode_health()

    assert outcome == "PENDING"
    component = engine.health.components[COMPONENT]
    assert component["ok"] is False
    detail = component["detail"]
    assert "EPISODE_MATERIALIZATION_PENDING" in detail
    # Must NOT claim the lifecycle is corrupt, impossible or failed.
    assert "FAILED" not in detail
    assert "corrupt" not in detail.lower()


# ------------------------------------------------------------------ H2
async def test_H2_retry_self_heals_health_without_restart(database):
    """H2: pending -> retry creates the Episode -> next refresh is HEALTHY."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h2")

    assert await engine._refresh_trade_episode_health() == "PENDING"
    assert engine.health.components[COMPONENT]["ok"] is False

    # The engine's own bounded retry (no manual second mechanism).
    created = await engine._retry_episode_materialization()
    assert created == 1

    assert await engine._refresh_trade_episode_health() == "HEALTHY"
    assert engine.health.components[COMPONENT]["ok"] is True
    assert await _count(database, TradeEpisodeORM) == 1


# ------------------------------------------------------------------ H3
async def test_H3_health_is_fact_driven_not_retry_return_path(database):
    """H3: Episode appears via another legal path -> refresh notices it.

    The retry is never invoked here, so passing proves health re-reads durable
    state instead of trusting a retry return value.
    """
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h3")

    assert await engine._refresh_trade_episode_health() == "PENDING"
    assert engine.health.components[COMPONENT]["ok"] is False

    # Materialise outside this engine's retry path.
    await _add_episode_directly(database, "plan_h3")

    assert await engine._refresh_trade_episode_health() == "HEALTHY"
    assert engine.health.components[COMPONENT]["ok"] is True


# ------------------------------------------------------------------ H4
async def test_H4_retry_exhausted_reports_materialization_failed(database):
    """H4: budget spent, still no Episode -> FAILED with actionable detail."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h4", complete=False)

    # Spend the attempt budget through the real retry path.
    for _ in range(engine._episode_retry_max_attempts + 1):
        await engine._retry_episode_materialization()

    state = engine._episode_retry_state["plan_h4"]
    assert state["attempts"] >= engine._episode_retry_max_attempts

    outcome = await engine._refresh_trade_episode_health()
    assert outcome == "FAILED"
    detail = engine.health.components[COMPONENT]["detail"]
    assert "EPISODE_MATERIALIZATION_FAILED" in detail
    assert "trade_plan_id=plan_h4" in detail
    assert f"max_attempts={engine._episode_retry_max_attempts}" in detail
    # Health observes only: it must never fabricate the missing Episode.
    assert await _count(database, TradeEpisodeORM) == 0


# ------------------------------------------------------------------ H5
async def test_H5_restart_recovery_heals_stale_health(database):
    """H5: a fresh engine (restart) must not inherit stale health."""
    await _add_closed_plan(database, "plan_h5")
    await _add_episode_directly(database, "plan_h5")

    first = make_paper_engine(database, engine_tick_seconds=3600)
    # Simulate the stale close-time verdict from the previous process.
    first.health.set(COMPONENT, False, "closed lifecycle lacks factual lineage")

    restarted = make_paper_engine(database, engine_tick_seconds=3600)
    assert restarted._episode_retry_state == {}
    assert await restarted._refresh_trade_episode_health() == "HEALTHY"
    assert restarted.health.components[COMPONENT]["ok"] is True


# ------------------------------------------------------------------ H6
async def test_H6_health_refresh_mutates_no_trading_facts(database):
    """H6: refresh is read-only with respect to every trading fact."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h6a")
    await _add_closed_plan(database, "plan_h6b", complete=False)

    async def snapshot():
        return (
            await _count(database, OrderORM),
            await _count(database, FillORM),
            await _count(database, TradeEpisodeORM),
            await _count(database, TradePlanORM),
        )

    before = await snapshot()
    state_before = {k: dict(v) for k, v in engine._episode_retry_state.items()}

    for _ in range(3):
        await engine._refresh_trade_episode_health()

    assert await snapshot() == before, "health refresh mutated durable facts"
    # Observation must not spend the retry budget either.
    assert {k: dict(v) for k, v in engine._episode_retry_state.items()} == state_before


# ------------------------------------------------------------------ H7
async def test_H7_multi_plan_aggregation_is_worst_state_wins(database):
    """H7: PENDING must not be masked by a healthy sibling, nor PENDING by FAILED."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h7_ok")
    await _add_episode_directly(database, "plan_h7_ok")
    await _add_closed_plan(database, "plan_h7_pending")

    # One Episode exists, one plan still pending -> PENDING, not HEALTHY.
    assert await engine._refresh_trade_episode_health() == "PENDING"

    # Add a plan whose budget is spent -> the aggregate becomes FAILED.
    await _add_closed_plan(database, "plan_h7_failed", complete=False)
    for _ in range(engine._episode_retry_max_attempts + 1):
        await engine._retry_episode_materialization()

    assert await engine._refresh_trade_episode_health() == "FAILED"
    detail = engine.health.components[COMPONENT]["detail"]
    assert "trade_plan_id=plan_h7_failed" in detail
    # The successfully materialised plan is still there and still counted once.
    assert await _count(database, TradeEpisodeORM) == 1


# ------------------------------------------------------------------ H8
async def test_H8_refresh_is_idempotent(database):
    """H8: repeated refreshes are stable, side-effect free and non-duplicating."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await _add_closed_plan(database, "plan_h8")
    await _add_episode_directly(database, "plan_h8")

    outcomes = [await engine._refresh_trade_episode_health() for _ in range(5)]
    assert outcomes == ["HEALTHY"] * 5
    assert await _count(database, TradeEpisodeORM) == 1

    async with database.session_factory() as session:
        rows = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(rows) == 1
    assert engine.health.components[COMPONENT]["ok"] is True


# ------------------------------------------------------------------ wiring
async def test_reconciliation_loop_wires_the_refresh(database):
    """The refresh must be wired onto the existing reconciliation cadence."""
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    source = inspect.getsource(TradingEngine._reconciliation_loop)
    assert "_retry_episode_materialization" in source
    assert "_refresh_trade_episode_health" in source
    assert source.index("_retry_episode_materialization") < source.index(
        "_refresh_trade_episode_health"
    ), "health must be refreshed AFTER the retry pass"


async def test_retry_budget_constants_are_unchanged(database):
    """The fix must not touch the retry contract."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    assert engine._episode_retry_max_attempts == 5
    assert engine._episode_retry_window_seconds == 300.0
