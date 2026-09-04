from __future__ import annotations

from decimal import Decimal

import pytest

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
    )
    duplicate = await plans.create(
        decision_id="decision_1",
        symbol="BTCUSDT",
        direction="LONG",
        thesis="ignored duplicate payload",
        requested_quantity=Decimal("0.2"),
    )

    assert first.trade_plan_id == duplicate.trade_plan_id
    assert first.state == TradePlanState.PLANNED
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
