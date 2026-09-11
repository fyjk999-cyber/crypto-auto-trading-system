"""P1-C: factual orphan positions recover only through RECOVERY plans."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.models import Position
from crypto_trader.persistence.models import LedgerTransactionORM
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine


def _orphan() -> Position:
    return Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("0.5"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("50"),
        instrument_type="LINEAR_PERP",
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )


async def test_orphan_position_creates_idempotent_recovery_plan_without_fills(database):
    engine = make_paper_engine(database)
    await engine.adapter.connect()
    engine.adapter.positions["BTCUSDT"] = _orphan()
    orders_before = dict(engine.adapter.orders)

    created = await engine._ensure_orphan_recovery_plans()
    assert len(created) == 1
    plan = await TradePlanService(database.session_factory).get_active_for_symbol(
        "BTCUSDT"
    )
    assert plan is not None
    assert plan.state == TradePlanState.RECOVERY
    assert plan.decision_id == "orphan_recovery_BTCUSDT"
    assert plan.direction == "LONG"
    assert plan.max_holding_time_seconds == 1.0
    assert engine.adapter.orders == orders_before

    # No fabricated fill/ledger settlement occurred.
    async with database.session_factory() as session:
        assert (
            await session.execute(select(LedgerTransactionORM))
        ).scalars().all() == []

    # Idempotent restart/retry returns the same recovery lifecycle.
    again = await engine._ensure_orphan_recovery_plans()
    assert again == []  # existing RECOVERY plan is reused
    second_engine = make_paper_engine(database)
    await second_engine.adapter.connect()
    second_engine.adapter.positions["BTCUSDT"] = _orphan()
    restart_created = await second_engine._ensure_orphan_recovery_plans()
    assert restart_created == []  # restart reuses the same lifecycle
    active = await TradePlanService(database.session_factory).get_active_for_symbol(
        "BTCUSDT"
    )
    assert active is not None and active.trade_plan_id == plan.trade_plan_id


async def test_recovery_plan_is_visible_to_position_manager_review(database):
    engine = make_paper_engine(database)
    await engine.adapter.connect()
    engine.adapter.positions["BTCUSDT"] = _orphan()
    await engine._ensure_orphan_recovery_plans()
    plan = await engine.trade_plans.get_active_for_symbol("BTCUSDT")
    assert plan is not None and plan.state == TradePlanState.RECOVERY
    # The normal OPEN-position manager receives the recovery plan; no direct
    # order/fill path exists in orphan recovery itself.
    assert plan.requested_quantity == Decimal("0.5")
    assert plan.exit_conditions == ["FACTUAL_ZERO_POSITION"]
