"""Real close-side settlement recovery: exit fill settled, plan never closed.

The previous close-side test forced an ENTRY fill's plan back to APPROVED, which
is not a close-side crash at all. This one drives a REAL lifecycle - factual
entry fill, ACTIVE plan, position decision, factual exit fill, position ZERO -
and then reproduces the genuine interruption point:

    exit FillORM exists
    exit ledger settlement exists
    position projection is zero
    ... but the TradePlan was never CLOSED and no TradeEpisode exists

Restart must converge to CLOSED with EXACTLY ONE episode, and a second restart
must reproduce the same episode identity and economics (no duplicate fee, no
duplicate ledger posting, no duplicate episode).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import (
    FillORM,
    LedgerTransactionORM,
    PositionProjectionORM,
    TradeEpisodeORM,
    TradePlanORM,
)
from crypto_trader.trade_plan.service import TradePlanService
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import (
    BTC_EXECUTION_METADATA,
    Evidence,
    MutableClock,
    SequencedChief,
    _seed_known_zero_funding_coverage,
)

SYMBOL = "BTCUSDT"


async def _open_lifecycle(database, engine, *, decisions_id="close-entry"):
    """Entry decision -> ACTIVE plan with a factual fill."""
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id=decisions_id,
        symbol=SYMBOL,
        action="LONG",
        market_regime="TREND",
        thesis="entry",
        position_size_request=0.1,
        leverage_request=10,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="entry-v1")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"), execution_metadata=BTC_EXECUTION_METADATA
    )
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    return plan


async def _run_to_closed(database):
    """Drive a full ENTRY -> position -> EXIT -> CLOSED lifecycle."""
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-close-1")
    plan = await _open_lifecycle(database, engine)

    async with database.session_factory() as session:
        active = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
    await _seed_known_zero_funding_coverage(database, active)

    from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    engine.position_manager = LiveLLMPositionManager(
        chief=SequencedChief([("EXIT", "0")]),
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    await engine.tick()
    await engine.wait_for_event_queue()
    return engine, plan


async def _counts(database, plan_id):
    async with database.session_factory() as session:
        fills = (await session.execute(select(FillORM))).scalars().all()
        ledger = (await session.execute(select(LedgerTransactionORM))).scalars().all()
        episodes = (
            await session.execute(
                select(TradeEpisodeORM).where(TradeEpisodeORM.trade_plan_id == plan_id)
            )
        ).scalars().all()
        position = (
            await session.execute(
                select(PositionProjectionORM).where(PositionProjectionORM.symbol == SYMBOL)
            )
        ).scalar_one_or_none()
        plan = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan_id)
            )
        ).scalar_one()
        return {
            "fill_ids": sorted(f.fill_id for f in fills),
            "fill_count": len(fills),
            "ledger_count": len(ledger),
            "fee_total": sum((f.fee or Decimal("0")) for f in fills),
            "episode_ids": sorted(e.episode_id for e in episodes),
            "episode_count": len(episodes),
            "position_qty": None if position is None else Decimal(str(position.quantity)),
            "plan_state": plan.state,
        }


def _episode_economics(episode):
    return {
        "episode_id": episode.episode_id,
        "order_ids": list(episode.order_ids_json or []),
        "fill_ids": list(episode.fill_ids_json or []),
        "entry_decision_id": episode.entry_decision_id,
        "exit_decision_id": episode.exit_decision_id,
        "opened_quantity": str(episode.opened_quantity),
        "closed_quantity": str(episode.closed_quantity),
    }


@pytest.mark.asyncio
async def test_real_close_side_interruption_recovers_to_one_episode(database):
    """§10-§13: real exit fill, plan not closed, episode absent -> recover."""
    engine, plan = await _run_to_closed(database)

    closed = await _counts(database, plan.trade_plan_id)
    assert closed["position_qty"] == 0, "precondition: the exit must flatten the position"
    assert closed["plan_state"] == "CLOSED", "precondition: the lifecycle must close normally"
    assert closed["episode_count"] == 1, "precondition: exactly one episode"
    assert len(closed["fill_ids"]) >= 2, "precondition: entry AND exit fills must exist"

    async with database.session_factory() as session:
        episode = (
            await session.execute(
                select(TradeEpisodeORM).where(TradeEpisodeORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        economics = _episode_economics(episode)

    # Reproduce the REAL interruption: exit fill and its settlement are durable,
    # the position is zero, but the plan was never closed and no episode exists.
    async with database.session_factory() as session:
        episode = (
            await session.execute(
                select(TradeEpisodeORM).where(TradeEpisodeORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        await session.delete(episode)
        row = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == plan.trade_plan_id)
            )
        ).scalar_one()
        row.state = "ACTIVE"
        row.closed_at = None
        row.terminal_reason = None
        await session.commit()

    interrupted = await _counts(database, plan.trade_plan_id)
    assert interrupted["plan_state"] == "ACTIVE"
    assert interrupted["episode_count"] == 0
    assert interrupted["position_qty"] == 0
    assert interrupted["fill_count"] == closed["fill_count"]

    await engine.stop()

    # --- first recovery: a fresh engine must converge from durable state alone
    recovered = make_paper_engine(database, engine_tick_seconds=3600)
    await recovered.start("run-close-1b")
    try:
        after_first = await _counts(database, plan.trade_plan_id)
        assert after_first["plan_state"] == "CLOSED", "recovery did not close the plan"
        assert after_first["episode_count"] == 1, (
            f"expected exactly one episode, got {after_first['episode_count']}"
        )
        assert after_first["fill_count"] == closed["fill_count"], "a fill was duplicated"
        assert after_first["ledger_count"] == closed["ledger_count"], (
            "a ledger posting was duplicated"
        )
        assert after_first["fee_total"] == closed["fee_total"], "a fee was duplicated"
        assert after_first["fill_ids"] == closed["fill_ids"]

        async with database.session_factory() as session:
            episode = (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.trade_plan_id == plan.trade_plan_id
                    )
                )
            ).scalar_one()
            first_econ = _episode_economics(episode)
    finally:
        await recovered.stop()

    # --- second restart: identity and economics must be identical
    again = make_paper_engine(database, engine_tick_seconds=3600)
    await again.start("run-close-1c")
    try:
        after_second = await _counts(database, plan.trade_plan_id)
        assert after_second["episode_count"] == 1, "the second restart duplicated an episode"
        assert after_second["fill_count"] == closed["fill_count"]
        assert after_second["ledger_count"] == closed["ledger_count"]
        assert after_second["fee_total"] == closed["fee_total"]
        assert after_second["fill_ids"] == closed["fill_ids"]
        assert after_second["episode_ids"] == after_first["episode_ids"], (
            "the second restart produced a different episode"
        )

        async with database.session_factory() as session:
            episode = (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.trade_plan_id == plan.trade_plan_id
                    )
                )
            ).scalar_one()
            second_econ = _episode_economics(episode)
    finally:
        await again.stop()

    assert second_econ["episode_id"] == first_econ["episode_id"]
    assert second_econ["order_ids"] == first_econ["order_ids"]
    assert second_econ["fill_ids"] == first_econ["fill_ids"]
    assert second_econ["entry_decision_id"] == economics["entry_decision_id"]
    assert second_econ["exit_decision_id"] == economics["exit_decision_id"]
    assert second_econ["opened_quantity"] == economics["opened_quantity"]
    assert second_econ["closed_quantity"] == economics["closed_quantity"]
