"""AAVE-shaped multi-fill safety exit, confined to temporary PAPER fixtures."""

import traceback
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, update

from crypto_trader.domain.enums import ExchangeEventType, OrderSide, TradingMode
from crypto_trader.domain.models import ExchangeEvent, OrderIntent
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.market_data.state import MarketState
from crypto_trader.persistence.models import (
    AuditEventORM,
    LedgerTransactionORM,
    LLMDecisionORM,
    OrderORM,
    RiskDecisionORM,
)
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import _open_v2_position


def _observer_module():
    """Load the future-observer classifier exactly as the script ships it."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "final_acceptance_lifecycle",
        Path(__file__).resolve().parents[2] / "scripts" / "acceptance" / "final_acceptance.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProfitFixtureExchange(SimulatedExchangeAdapter):
    """External market boundary fixture; actual matching/settlement untouched."""

    profitable = False
    generation = 0

    async def get_market_state(self, symbol):
        self.generation += 1
        price = Decimal("101.2") if self.profitable else Decimal("100")
        return MarketState(
            symbol=symbol,
            provider="ISOLATED_FIXTURE",
            data_source="ISOLATED_FIXTURE",
            health="HEALTHY",
            status="HEALTHY",
            freshness="HEALTHY",
            mark_price=price,
            price=price,
            best_bid=price - Decimal("0.01"),
            best_ask=price + Decimal("0.01"),
            generation=self.generation,
            taker_buy_volume=Decimal("500"),
            taker_sell_volume=Decimal("800"),
            cvd=Decimal("-300"),
            trade_count=120,
            large_trade_count=3,
            largest_trade_notional=Decimal("150000"),
            imbalance_l5=Decimal("-0.4"),
            realized_volatility=Decimal("0.002"),
        )


@pytest.mark.parametrize("fill_before_ack", [False, True])
async def test_inline_events_settle_before_submit_returns(database, fill_before_ack):
    """Deliver the real simulator events before the submit response binds its ID."""
    class InlineExchange(ProfitFixtureExchange):
        async def _emit(self, event):
            await super()._emit(event)
            await engine.wait_for_event_queue()

    adapter = InlineExchange(initial_balances={"USDT": Decimal("100000")})
    adapter.fill_before_ack = fill_before_ack
    engine = make_paper_engine(database, simulator=adapter, engine_tick_seconds=3600)
    await engine.start("isolated-inline-events")
    try:
        adapter.seed_book("BTCUSDT", mid="100", spread="0.01", depth=10)
        await engine._strategy_context("BTCUSDT")
        await _open_v2_position(
            engine, LLMDecisionStore(database.session_factory),
            TradePlanService(database.session_factory), "inline-entry", 10.0,
        )
        native = next(iter(adapter.orders.values()))
        durable = await engine.order_manager.get_by_client(native.client_order_id)
        position = await engine.portfolio.get_position("BTCUSDT")
        assert native.filled_quantity == Decimal("10")
        assert durable.filled_quantity == Decimal("10")
        assert position is not None and position.quantity == Decimal("10")
        assert engine.settlement.snapshot()["state"] == "COHERENT"
    finally:
        await engine.stop()


@pytest.mark.parametrize("conflict", ["symbol", "side", "exchange_order_id"])
async def test_early_event_cannot_rebind_conflicting_order(database, conflict):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("isolated-event-identity")
    try:
        order = await engine.order_manager.create_from_intent(
            OrderIntent(client_order_id="known-client", symbol="BTCUSDT",
                        side=OrderSide.BUY, price="100", quantity="1"),
            trading_mode=TradingMode.PAPER,
        )
        await engine.order_manager.validate(order.internal_order_id)
        await engine.order_manager.submitting(order.internal_order_id)
        await engine.order_manager.submitted(order.internal_order_id)
        if conflict == "exchange_order_id":
            await engine.order_manager.ack(order.internal_order_id, "original-exchange")
        payload = {"client_order_id": order.client_order_id,
                   "exchange_order_id": "early-exchange", "side": "BUY"}
        if conflict == "side":
            payload["side"] = "SELL"
        incoming = ExchangeEvent(
            event_id="isolated-conflict", event_type=ExchangeEventType.ORDER_ACK,
            symbol="ETHUSDT" if conflict == "symbol" else "BTCUSDT",
            timestamp=datetime.now(UTC), payload=payload,
        )
        with pytest.raises(ValueError, match="EXCHANGE_EVENT_ORDER_IDENTITY_CONFLICT"):
            await engine.process_exchange_event(incoming)
        durable = await engine.order_manager.get(order.internal_order_id)
        assert durable.exchange_order_id == (
            "original-exchange" if conflict == "exchange_order_id" else None
        )
        assert durable.filled_quantity == Decimal("0")
    finally:
        await engine.stop()


async def test_startup_lifecycle_discovery_avoids_per_fill_audit_scan(database):
    captured = []

    def capture_query(conn, cursor, statement, parameters, context, executemany):
        if "FROM trade_plans JOIN positions_projection" in statement:
            captured.append((statement, parameters))

    event.listen(database.engine.sync_engine, "before_cursor_execute", capture_query)
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    try:
        await engine.start("isolated-startup-query-cost")
        assert len(captured) == 1
        async with database.engine.connect() as connection:
            plan = (
                await connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN " + captured[0][0], captured[0][1]
                )
            ).all()
        assert plan
        assert not any("SCAN audit_events" in row[3] for row in plan), plan
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", capture_query)
        await engine.stop()


@pytest.mark.parametrize(
    "recovery_case",
    [
        "normal",
        "normal_missing_exit_decision",
        "normal_missing_episode_lineage",
        "legacy",
        "legacy_missing_intent",
        "legacy_missing_entry",
        "legacy_missing_risk",
        "legacy_missing_ledger",
        "legacy_missing_pointer_target",
        "legacy_closed_missing_episode",
        "legacy_closed_missing_settled",
    ],
)
async def test_fast_profit_multifill_closes_plan_without_fake_llm_exit(database, recovery_case):
    legacy_recovery = recovery_case.startswith("legacy")
    adapter = ProfitFixtureExchange(initial_balances={"USDT": Decimal("100000")})
    engine = make_paper_engine(database, simulator=adapter, engine_tick_seconds=3600)
    await engine.start("isolated-deterministic-close")
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    try:
        adapter.seed_book("BTCUSDT", mid="100", spread="0.01", depth=10)
        await engine._strategy_context("BTCUSDT")
        plan = await _open_v2_position(engine, decisions, plans, "fixture-entry", 10)
        assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
        assert (await engine.portfolio.get_position("BTCUSDT")).quantity == Decimal("10")
        adapter.profitable = True
        book = adapter.seed_book("BTCUSDT", mid="101.2", spread="0.01")
        book.apply_snapshot(
            20,
            [
                (Decimal("101.19"), Decimal("2")),
                (Decimal("101.18"), Decimal("2")),
                (Decimal("101.17"), Decimal("2")),
                (Decimal("101.16"), Decimal("4")),
            ],
            [(Decimal("101.21"), Decimal("10"))],
        )
        failures = []
        actual_settlement = engine.order_manager.settlement_callback
        removed_entry = []

        def lose_entry_after_factual_close(
            conn, cursor, statement, parameters, context, executemany
        ):
            if (
                statement.lstrip().upper().startswith("UPDATE TRADE_PLANS")
                and "CLOSED" in parameters
            ):
                # Actual fixture DB loss between plan-close and episode reads;
                # never replace the real episode builder with a fake result.
                conn.exec_driver_sql(
                    "DELETE FROM llm_decisions WHERE decision_id=?", ("fixture-entry",)
                )
                removed_entry.append(True)

        if recovery_case == "normal_missing_episode_lineage":
            event.listen(
                database.engine.sync_engine, "after_cursor_execute", lose_entry_after_factual_close
            )

        def interrupt_final_close(conn, cursor, statement, parameters, context, executemany):
            if recovery_case == "legacy_closed_missing_settled":
                if (
                    statement.lstrip().upper().startswith("INSERT INTO AUDIT_EVENTS")
                    and "FILL_SETTLED" in parameters
                ):
                    raise RuntimeError("isolated failure at final settlement audit")
                return
            fault_table = (
                "FROM trade_episodes"
                if recovery_case == "legacy_closed_missing_episode"
                else "FROM llm_decisions"
            )
            if fault_table in statement:
                raise RuntimeError("isolated failure at lifecycle closure")

        if legacy_recovery:
            event.listen(
                database.engine.sync_engine, "before_cursor_execute", interrupt_final_close
            )

        async def capture_actual_failure(fill):
            if recovery_case == "normal_missing_exit_decision" and fill.quantity == Decimal("4"):
                # Missing factual metadata at the actual durable callback
                # boundary; no internal plan/episode result is substituted.
                async with database.session_factory() as session:
                    row = await session.get(OrderORM, fill.order_id)
                    row.metadata_json = {**row.metadata_json, "decision_id": None}
                    await session.commit()
            try:
                return await actual_settlement(fill)
            except Exception as exc:
                failures.append(
                    {
                        "class": type(exc).__name__,
                        "message": str(exc),
                        "source": traceback.extract_tb(exc.__traceback__)[-1].name,
                    }
                )
                raise

        engine.order_manager.settlement_callback = capture_actual_failure
        risks = await engine.tick()  # Real deterministic controller -> Risk -> authority.
        await engine.wait_for_event_queue()
        if recovery_case == "normal_missing_episode_lineage":
            event.remove(
                database.engine.sync_engine, "after_cursor_execute", lose_entry_after_factual_close
            )
        if legacy_recovery:
            event.remove(
                database.engine.sync_engine, "before_cursor_execute", interrupt_final_close
            )
        assert risks and risks[0].reason == "RISK_PASS"
        orders = await engine.order_manager.list_all()
        exits = [o for o in orders if o.metadata.get("reduce_only") is True]
        assert len(exits) == 1
        assert exits[0].metadata["lifecycle_action"] == "FAST_PROFIT_PROTECTION"
        if recovery_case == "normal":
            audit_id = exits[0].metadata.get("exit_intent_audit_id")
            assert isinstance(audit_id, str) and audit_id
            audits = await engine.audit.list_recent(limit=200)
            matching = [a for a in audits if a.audit_event_id == audit_id]
            assert len(matching) == 1
            assert matching[0].action == "DETERMINISTIC_EXIT_INTENT"
            assert matching[0].client_order_id == exits[0].client_order_id
            # The future observer's canonical classifier must accept the real
            # engine-emitted metadata, and reject a forged authority.
            observer = _observer_module()
            assert observer.order_violation(exits[0].metadata, "PAPER", "FILLED") is False
            assert (
                observer.order_violation(
                    {**exits[0].metadata, "exit_authority": "UNKNOWN_AUTHORITY"},
                    "PAPER",
                    "FILLED",
                )
                is True
            )
        assert exits[0].filled_quantity == Decimal("10")
        exit_events = [
            e
            for e in adapter.event_log
            if e.payload.get("client_order_id") == exits[0].client_order_id
            and "fill_quantity" in e.payload
        ]
        assert [e.payload["fill_quantity"] for e in exit_events] == ["2", "2", "2", "4"]
        assert (await engine.portfolio.get_position("BTCUSDT")).quantity == 0
        if recovery_case == "normal_missing_exit_decision":
            assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
            assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
            assert engine.trading_safety_failures()
            audits = await engine.audit.list_recent(limit=200)
            assert not any(
                a.action == "FILL_SETTLED" and a.target == exit_events[-1].payload["fill_id"]
                for a in audits
            )
            return
        if recovery_case == "normal_missing_episode_lineage":
            assert removed_entry
            assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.CLOSED
            assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
            assert engine.trading_safety_failures()
            audits = await engine.audit.list_recent(limit=200)
            assert not any(
                a.action == "FILL_SETTLED" and a.target == exit_events[-1].payload["fill_id"]
                for a in audits
            )
            return
        assert await decisions.get(exits[0].metadata["decision_id"]) is None
        if legacy_recovery:
            expected_state = (
                TradePlanState.CLOSED
                if recovery_case.startswith("legacy_closed_")
                else TradePlanState.ACTIVE
            )
            assert (await plans.get(plan.trade_plan_id)).state == expected_state
            await engine.stop()
            # Dataset fixture for the actual pre-coordinator production shape:
            # that release never had these engineering journal event types.
            # Remove only fixture-only journal records, never factual fills,
            # Risk/intent evidence or ledger. No production DB is accessed.
            async with database.session_factory() as session:
                exit_row = await session.get(OrderORM, exits[0].internal_order_id)
                legacy_metadata = dict(exit_row.metadata_json)
                if recovery_case == "legacy_missing_pointer_target":
                    legacy_metadata["exit_intent_audit_id"] = "fixture-nonexistent-audit"
                else:
                    # Old deployed orders never had this new indexed pointer.
                    legacy_metadata.pop("exit_intent_audit_id", None)
                exit_row.metadata_json = legacy_metadata
                await session.execute(
                    delete(AuditEventORM).where(
                        AuditEventORM.action.in_(
                            ["SETTLEMENT_EXTERNAL_BEGIN", "SETTLEMENT_EXTERNAL_COMPLETE"]
                        )
                    )
                )
                if recovery_case == "legacy_missing_intent":
                    await session.execute(
                        delete(AuditEventORM).where(
                            AuditEventORM.action == "DETERMINISTIC_EXIT_INTENT"
                        )
                    )
                if recovery_case == "legacy_missing_entry":
                    await session.execute(
                        delete(LLMDecisionORM).where(LLMDecisionORM.decision_id == "fixture-entry")
                    )
                if recovery_case == "legacy_missing_risk":
                    await session.execute(
                        delete(RiskDecisionORM).where(
                            RiskDecisionORM.risk_decision_id
                            == exits[0].metadata["risk_decision_id"]
                        )
                    )
                if recovery_case == "legacy_missing_ledger":
                    await session.execute(
                        update(LedgerTransactionORM)
                        .where(LedgerTransactionORM.fill_id == exit_events[-1].payload["fill_id"])
                        .values(fill_id="fixture-unbound-ledger-fill")
                    )
                await session.commit()
            engine = make_paper_engine(
                database, simulator=ProfitFixtureExchange(), engine_tick_seconds=3600
            )
            await engine.start("isolated-legacy-lifecycle-recovery")
            if recovery_case.startswith("legacy_missing_"):
                assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.ACTIVE
                assert await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id) is None
                assert engine.settlement.snapshot()["state"] == "SETTLEMENT_FAULT"
                assert engine.trading_safety_failures()
                assert engine.runtime_snapshot()["health"]["overall"] == "UNHEALTHY"
                return
            # Second restart: lifecycle recovery must be idempotent, never
            # duplicate episodes, ledger entries or FILL_SETTLED evidence.
            entries_before = {
                entry.entry_id for entry in await engine.ledger.list_entries_recent(limit=200)
            }
            await engine.stop()
            engine = make_paper_engine(
                database, simulator=ProfitFixtureExchange(), engine_tick_seconds=3600
            )
            await engine.start("isolated-legacy-lifecycle-recovery-second")
            assert {
                entry.entry_id for entry in await engine.ledger.list_entries_recent(limit=200)
            } == entries_before
            recovery_audits = await engine.audit.list_recent(limit=300)
            settled_targets = [
                audit.target for audit in recovery_audits if audit.action == "FILL_SETTLED"
            ]
            assert len(settled_targets) == len(set(settled_targets))
            assert (await plans.get(plan.trade_plan_id)).state == TradePlanState.CLOSED
            assert engine.settlement.snapshot()["state"] == "COHERENT"
        closed = await plans.get(plan.trade_plan_id)
        assert closed.state == TradePlanState.CLOSED, failures
        # Read-only public store query must observe recovery's episode; calling
        # the builder here first would hide a missing startup finalization.
        episodes = await engine.trade_episodes.load_closed_on(
            closed.closed_at.date().isoformat(), timezone=UTC
        )
        assert len([e for e in episodes if e.trade_plan_id == plan.trade_plan_id]) == 1
        episode = await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id)
        again = await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id)
        assert episode is not None and again.episode_id == episode.episode_id
        assert episode.exit_decision_id == exits[0].metadata["decision_id"]
        assert episode.net_pnl == Decimal("9.15773")  # Worked fixture fill prices and fees.
        if recovery_case == "legacy_closed_missing_settled":
            audits = await engine.audit.list_recent(limit=200)
            settled = {a.target for a in audits if a.action == "FILL_SETTLED"}
            assert {e.payload["fill_id"] for e in exit_events} <= settled
        assert engine.settlement.snapshot()["state"] == "COHERENT"
    finally:
        await engine.stop()


class RiskCrashExchange(ProfitFixtureExchange):
    """Isolated fixture mark crash; actual matching/settlement untouched."""

    crash = False

    async def get_market_state(self, symbol):
        state = await super().get_market_state(symbol)
        price = Decimal("92") if self.crash else Decimal("100")
        return state.model_copy(
            update={
                "price": price,
                "mark_price": price,
                "best_bid": price - Decimal("0.01"),
                "best_ask": price + Decimal("0.01"),
            }
        )


async def test_risk_hard_exit_closes_plan_with_typed_provenance(database):
    adapter = RiskCrashExchange(initial_balances={"USDT": Decimal("100000")})
    engine = make_paper_engine(database, simulator=adapter, engine_tick_seconds=3600)
    await engine.start("isolated-risk-hard-exit")
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    try:
        adapter.seed_book("BTCUSDT", mid="100", spread="0.01", depth=10)
        await engine._strategy_context("BTCUSDT")
        plan = await _open_v2_position(engine, decisions, plans, "fixture-entry", 10)
        adapter.crash = True
        book = adapter.seed_book("BTCUSDT", mid="92", spread="0.01")
        book.apply_snapshot(
            50,
            [(Decimal("92.0"), Decimal("10"))],
            [(Decimal("92.02"), Decimal("10"))],
        )
        risks = await engine.tick()
        await engine.wait_for_event_queue()
        assert risks and risks[0].reason == "RISK_PASS"
        exits = [
            order
            for order in await engine.order_manager.list_all()
            if order.metadata.get("reduce_only") is True
        ]
        assert len(exits) == 1
        assert exits[0].metadata["lifecycle_action"] == "RISK_HARD_EXIT"
        assert exits[0].metadata["exit_authority"] == "RISK_HARD_EXIT"
        assert exits[0].filled_quantity == Decimal("10")
        assert (await engine.portfolio.get_position("BTCUSDT")).quantity == 0
        closed = await plans.get(plan.trade_plan_id)
        assert closed.state == TradePlanState.CLOSED
        episode = await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id)
        assert episode is not None
        assert engine.settlement.snapshot()["state"] == "COHERENT"
    finally:
        await engine.stop()


async def test_partial_exit_cancel_releases_reservation_and_closes_once(database):
    """A cancelled partial protection exit must not strand the remaining position."""
    adapter = ProfitFixtureExchange(initial_balances={"USDT": Decimal("100000")})
    engine = make_paper_engine(database, simulator=adapter, engine_tick_seconds=3600)
    await engine.start("isolated-partial-exit-cancel")
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    try:
        adapter.seed_book("BTCUSDT", mid="100", spread="0.01", depth=10)
        await engine._strategy_context("BTCUSDT")
        plan = await _open_v2_position(engine, decisions, plans, "fixture-entry", 10)
        adapter.profitable = True
        book = adapter.seed_book("BTCUSDT", mid="101.2", spread="0.01")
        book.apply_snapshot(
            40,
            [(Decimal("101.19"), Decimal("2")), (Decimal("101.18"), Decimal("2"))],
            [(Decimal("101.21"), Decimal("10"))],
        )
        risks = await engine.tick()  # Real deterministic controller -> Risk -> authority.
        await engine.wait_for_event_queue()
        assert risks and risks[0].reason == "RISK_PASS"
        exits = [
            order
            for order in await engine.order_manager.list_all()
            if order.metadata.get("reduce_only") is True
        ]
        assert len(exits) == 1
        assert exits[0].filled_quantity == Decimal("4")
        assert (await engine.portfolio.get_position("BTCUSDT")).quantity == Decimal("6")
        # The resting remainder is factually cancelled: its reservation must be
        # released so the still-open 6 can be protected by a new factual exit.
        await adapter.cancel_order("BTCUSDT", exits[0].exchange_order_id)
        await engine.wait_for_event_queue()
        assert (await engine.order_manager.get(exits[0].internal_order_id)).status.value == (
            "CANCELLED"
        )
        book.apply_snapshot(
            41, [(Decimal("101.19"), Decimal("6"))], [(Decimal("101.21"), Decimal("10"))]
        )
        risks = await engine.tick()
        await engine.wait_for_event_queue()
        assert risks and risks[0].reason == "RISK_PASS"
        exits = sorted(
            [
                order
                for order in await engine.order_manager.list_all()
                if order.metadata.get("reduce_only") is True
            ],
            key=lambda order: order.created_at,
        )
        assert len(exits) == 2
        assert exits[0].filled_quantity == Decimal("4")
        assert exits[1].filled_quantity == Decimal("6")
        assert exits[1].metadata["decision_id"] != exits[0].metadata["decision_id"]
        assert (await engine.portfolio.get_position("BTCUSDT")).quantity == 0
        closed = await plans.get(plan.trade_plan_id)
        assert closed.state == TradePlanState.CLOSED
        episode = await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id)
        again = await engine.trade_episodes.build_for_closed_plan(plan.trade_plan_id)
        assert episode is not None and again.episode_id == episode.episode_id
        assert engine.settlement.snapshot()["state"] == "COHERENT"
        audits = await engine.audit.list_recent(limit=300)
        settled = {audit.target for audit in audits if audit.action == "FILL_SETTLED"}
        exit_fills = {
            event.payload["fill_id"]
            for event in adapter.event_log
            if event.payload.get("client_order_id") in {o.client_order_id for o in exits}
            and "fill_quantity" in event.payload
        }
        assert exit_fills and exit_fills <= settled
        # Idempotent: a factual zero position creates no further exit order.
        assert await engine.tick() == []
        assert (
            len(
                [
                    order
                    for order in await engine.order_manager.list_all()
                    if order.metadata.get("reduce_only") is True
                ]
            )
            == 2
        )
    finally:
        await engine.stop()
