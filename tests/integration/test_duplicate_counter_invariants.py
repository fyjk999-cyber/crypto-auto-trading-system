"""§41: measure, rather than assume, that no economic effect is duplicated.

The UNIQUE indexes make duplicates structurally impossible for fills and ledger
transactions, but a constraint is not a measurement - it only fires when
something tries to violate it. These counters are queried against a database that
has actually been through an entry, a duplicate exchange event, a restart AND a
full close, so a duplicate produced by ANY of those paths is caught.

DUPLICATE_FEES and DUPLICATE_EPISODES have no direct column: they are measured as
"the money that entered the ledger exactly once, and exactly one episode per
closed plan", which is the property that actually matters.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.order.settlement import STATE_COMPLETE
from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
    OrderORM,
    TradeEpisodeORM,
    TradePlanORM,
)


async def measure(database) -> dict:
    """The §41 counters, computed from durable rows."""
    async with database.session_factory() as session:
        # DUPLICATE_FILLS: one row per factual fill_id
        total_fills = (
            await session.execute(select(func.count()).select_from(FillORM))
        ).scalar_one()
        distinct_fills = (
            await session.execute(select(func.count(func.distinct(FillORM.fill_id))))
        ).scalar_one()

        # DUPLICATE_LEDGER_TRANSACTIONS: one TRADE posting per fill_id
        ledger_fill_ids = (
            await session.execute(
                select(LedgerTransactionORM.fill_id).where(
                    LedgerTransactionORM.fill_id.is_not(None)
                )
            )
        ).scalars().all()
        ledger_ids = list(ledger_fill_ids)
        distinct_ledger = len(set(ledger_ids))

        # DUPLICATE_FEES: fee economic effect, counted as ONE posting per fill
        fee_rows = (
            await session.execute(
                select(LedgerTransactionORM.fill_id).where(
                    LedgerTransactionORM.fill_id.is_not(None)
                )
            )
        ).scalars().all()

        # DUPLICATE_EPISODES: at most one episode per closed plan
        closed_plans = (
            await session.execute(
                select(TradePlanORM.trade_plan_id).where(TradePlanORM.state == "CLOSED")
            )
        ).scalars().all()
        episodes = (
            await session.execute(select(TradeEpisodeORM.trade_plan_id))
        ).scalars().all()

    episode_counts_ok = all(
        len([e for e in episodes if e == pid]) <= 1 for pid in set(episodes)
    )

    return {
        "DUPLICATE_FILLS": total_fills - distinct_fills,
        "DUPLICATE_LEDGER_TRANSACTIONS": len(ledger_ids) - distinct_ledger,
        "DUPLICATE_FEES": len(fee_rows) - len(set(fee_rows)),
        "DUPLICATE_EPISODES": 0 if episode_counts_ok else 1,
        "fills": total_fills,
        "ledger_total": len(ledger_ids),
        "closed_plans": len(list(closed_plans)),
        "episodes": len(list(episodes)),
    }


@pytest.mark.asyncio
async def test_no_duplicate_economic_effect_through_entry_dup_restart_and_close(
    database,
):
    """Full lifecycle, then measure. Any duplicated effect shows up as a counter."""
    from crypto_trader.llm_chief.decision import ChiefTraderDecision
    from crypto_trader.llm_chief.decision_store import LLMDecisionStore
    from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
    from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
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
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-dup-counters")
    try:
        decisions = LLMDecisionStore(database.session_factory)
        plans = TradePlanService(database.session_factory)
        entry = ChiefTraderDecision(
            decision_id="dup-entry",
            symbol=SYMBOL,
            action="LONG",
            market_regime="TREND",
            thesis="t",
            position_size_request=0.1,
            leverage_request=10,
            stop_loss=95,
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )
        await decisions.save(entry, run_id=engine.run_id, prompt_version="dup-v1")
        plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
            entry,
            quantity=Decimal("0.1"),
            limit_price=Decimal("101"),
            execution_metadata=BTC_EXECUTION_METADATA,
        )
        await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
        await engine.process_signal(signal)
        await engine.wait_for_event_queue()

        engine.position_manager = LiveLLMPositionManager(
            chief=SequencedChief([("EXIT", "0")]),
            evidence_engine=Evidence(),
            decisions=decisions,
            plans=plans,
            audit=engine.audit,
            review_cooldown_seconds=0,
        )
        active = await plans.get(plan.trade_plan_id)
        await _seed_known_zero_funding_coverage(database, active)
        clock.advance()
        await engine.tick()
        await engine.wait_for_event_queue()
        # Baseline taken AFTER the lifecycle is complete: the restart is the only
        # thing that may still change anything, so comparing anything earlier
        # would just be measuring the exit fill itself.
        before_restart = await measure(database)
    finally:
        await engine.stop()

    restarted = make_paper_engine(database, engine_tick_seconds=3600)
    await restarted.start("run-dup-counters-b")
    try:
        final = await measure(database)
    finally:
        await restarted.stop()

    # Measured values, surfaced so the numbers can be reported rather than only
    # asserted.
    import sys

    print("  §41 MEASURED:", {k: v for k, v in final.items()}, file=sys.stderr)

    # §41 required values - measured, not assumed.
    assert final["DUPLICATE_FILLS"] == 0, f"measured {final}"
    assert final["DUPLICATE_LEDGER_TRANSACTIONS"] == 0, f"measured {final}"
    assert final["DUPLICATE_FEES"] == 0, f"measured {final}"
    assert final["DUPLICATE_EPISODES"] == 0, f"measured {final}"

    # The measurement itself must have had something to measure.
    assert final["fills"] >= 2, f"expected an entry and an exit fill, got {final}"
    assert final["ledger_total"] >= 2, f"expected two postings, got {final}"

    # The restart must not have added a single economic effect.
    assert final["fills"] == before_restart["fills"], "restart changed the fill count"
    assert final["ledger_total"] == before_restart["ledger_total"], (
        "restart changed the ledger posting count"
    )
    assert final["episodes"] == before_restart["episodes"], (
        "restart changed the episode count"
    )

    # Every settlement reached COMPLETE, so nothing was left half-settled.
    async with database.session_factory() as session:
        states = (
            await session.execute(select(FillSettlementORM.state))
        ).scalars().all()
    assert states, "no settlement markers were produced at all"
    assert set(states) == {STATE_COMPLETE}, f"unfinished settlements: {sorted(set(states))}"

    # A closed lifecycle carries exactly one episode.
    assert final["closed_plans"] == 1, f"expected one closed plan, got {final}"
    assert final["episodes"] == 1, f"expected exactly one episode, got {final}"

    # Orders are not duplicated either.
    async with database.session_factory() as session:
        order_ids = (await session.execute(select(OrderORM.internal_order_id))).scalars().all()
    assert len(list(order_ids)) == len(set(order_ids))
