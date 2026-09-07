from __future__ import annotations

from decimal import Decimal

import pytest

from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.persistence.models import PositionProjectionORM
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState


async def test_trade_plan_is_idempotent_by_decision_id_and_has_terminal_semantics(database):
    plans = TradePlanService(database.session_factory)
    first = await plans.create(
        decision_id="decision_1",
        symbol="BTCUSDT",
        direction="LONG",
        thesis="breakout structure remains valid",
        requested_quantity=Decimal("0.1"),
        requested_leverage=Decimal("2"),
        requested_exposure=Decimal("500"),
        entry_conditions=["breakout confirmed"],
        invalidation_conditions=["close below support"],
        reduce_conditions=["momentum weakens"],
        exit_conditions=["thesis invalidated"],
        expected_holding_period="4h",
        max_holding_time_seconds=7200,
    )
    duplicate = await plans.create(
        decision_id="decision_1",
        symbol="BTCUSDT",
        direction="LONG",
        thesis="breakout structure remains valid",
        requested_quantity=Decimal("0.1"),
        requested_leverage=Decimal("2"),
        requested_exposure=Decimal("500"),
        entry_conditions=["breakout confirmed"],
        invalidation_conditions=["close below support"],
        reduce_conditions=["momentum weakens"],
        exit_conditions=["thesis invalidated"],
        expected_holding_period="4h",
        max_holding_time_seconds=7200,
    )

    assert first.trade_plan_id == duplicate.trade_plan_id
    assert first.state == TradePlanState.PLANNED
    assert first.requested_exposure == Decimal("500")
    assert first.invalidation_conditions == ["close below support"]
    assert first.max_holding_time_seconds == 7200
    with pytest.raises(ValueError, match="immutable TradePlan conflict"):
        await plans.create(
            decision_id="decision_1",
            symbol="BTCUSDT",
            direction="LONG",
            thesis="conflicting retry",
            requested_quantity=Decimal("0.2"),
        )
    rejected = await plans.transition(first.trade_plan_id, TradePlanState.REJECTED, reason="risk")
    assert rejected.terminal_reason == "risk"
    with pytest.raises(ValueError):
        await plans.transition(first.trade_plan_id, TradePlanState.ACTIVE)


async def test_trade_plan_rejects_planless_or_malformed_entry_proposals(database):
    plans = TradePlanService(database.session_factory)
    with pytest.raises(ValueError):
        await plans.create(
            decision_id="decision_2",
            symbol="BTCUSDT",
            direction="WAIT",
            thesis="not an entry",
            requested_quantity=Decimal("1"),
        )
    with pytest.raises(ValueError):
        await plans.create(
            decision_id="decision_3",
            symbol="BTCUSDT",
            direction="SHORT",
            thesis="invalid size",
            requested_quantity=Decimal("0"),
        )


async def test_trade_plan_can_be_retrieved_after_restart_boundary(database):
    plans = TradePlanService(database.session_factory)
    created = await plans.create(
        decision_id="decision_restart",
        symbol="ETHUSDT",
        direction="SHORT",
        thesis="thesis",
        requested_quantity=Decimal("1"),
    )
    recovered = await TradePlanService(database.session_factory).get(created.trade_plan_id)
    assert recovered == created


async def test_trade_plan_transition_matrix_fails_closed_and_is_idempotent(database):
    plans = TradePlanService(database.session_factory)
    plan = await plans.create(
        decision_id="decision_matrix", symbol="BTCUSDT", direction="LONG", thesis="x",
        requested_quantity=Decimal("1"),
    )
    same = await plans.transition(plan.trade_plan_id, TradePlanState.PLANNED)
    assert same.state == TradePlanState.PLANNED
    with pytest.raises(ValueError):
        await plans.transition(plan.trade_plan_id, TradePlanState.ACTIVE)
    approved = await plans.transition(plan.trade_plan_id, TradePlanState.APPROVED)
    assert approved.state == TradePlanState.APPROVED
    active = await plans.transition(plan.trade_plan_id, TradePlanState.ACTIVE)
    assert active.state == TradePlanState.ACTIVE
    with pytest.raises(ValueError):
        await plans.transition(plan.trade_plan_id, TradePlanState.INVALIDATED)
    with pytest.raises(ValueError, match="factual close method"):
        await plans.transition(plan.trade_plan_id, TradePlanState.CLOSED)
    exit_decision = ChiefTraderDecision(
        decision_id="position-exit",
        symbol="BTCUSDT",
        position_state=PositionState.OPEN,
        action="EXIT",
        market_regime="TREND",
    )
    decisions = LLMDecisionStore(database.session_factory)
    await decisions.save(
        exit_decision,
        run_id="run-matrix",
        prompt_version="open-v1",
        parent_decision_id="decision_matrix",
        position_context={
            "trade_plan_id": plan.trade_plan_id,
            "entry_decision_id": "decision_matrix",
        },
    )
    async with database.session_factory() as session:
        session.add(
            PositionProjectionORM(
                symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                quantity=Decimal("1"),
            )
        )
        await session.commit()
    with pytest.raises(ValueError, match="non-zero factual position"):
        await plans.close_from_factual_position(
            plan.trade_plan_id,
            exit_decision_id=exit_decision.decision_id,
            reason="EXIT",
        )
    async with database.session_factory() as session:
        position = (
            await session.get(PositionProjectionORM, 1)
        )
        assert position is not None
        position.quantity = Decimal("0")
        await session.commit()
    closed = await plans.close_from_factual_position(
        plan.trade_plan_id,
        exit_decision_id=exit_decision.decision_id,
        reason="EXIT",
    )
    assert closed.state == TradePlanState.CLOSED


async def test_trade_plan_entry_lineage_links_are_immutable_and_idempotent(database):
    plans = TradePlanService(database.session_factory)
    plan = await plans.create(
        decision_id="decision_lineage",
        symbol="ETHUSDT",
        direction="SHORT",
        thesis="factual entry lineage",
        requested_quantity=Decimal("2"),
    )
    linked = await plans.link(
        plan.trade_plan_id,
        signal_id="signal-1",
        risk_decision_id="risk-1",
        order_id="order-1",
    )
    same = await plans.link(
        plan.trade_plan_id,
        signal_id="signal-1",
        risk_decision_id="risk-1",
        order_id="order-1",
    )
    assert same == linked

    for field, replacement in (
        ("signal_id", "signal-2"),
        ("risk_decision_id", "risk-2"),
        ("order_id", "order-2"),
    ):
        with pytest.raises(ValueError, match="immutable TradePlan entry lineage"):
            await plans.link(plan.trade_plan_id, **{field: replacement})
    assert await plans.get(plan.trade_plan_id) == linked
