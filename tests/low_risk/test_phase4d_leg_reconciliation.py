"""Phase 4D: leg-level reconciliation is the gate for hedge execution."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    LegPositionReconciler,
    PositionLegService,
)

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation",
    base_exit={"type": "PRICE", "trigger": ">=110"},
    invalidation="close below 98",
    evidence_families=["trend"],
    reason="momentum entry",
)


async def _seed(service: PositionLegService, *, quantity: Decimal) -> None:
    await service.register(LONG, trade_plan_id="plan-long", quantity=quantity)


async def test_no_leg_activity_with_flat_net_is_matched(database) -> None:
    service = PositionLegService(database.session_factory)
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0"))
    assert result["status"] == "MATCHED"
    assert result["leg_execution_safe"] is True
    assert result["is_order"] is False
    assert result["authority"] == "RECONCILIATION_ONLY"


async def test_untracked_net_position_is_flagged(database) -> None:
    service = PositionLegService(database.session_factory)
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.5"))
    assert result["status"] == "UNTRACKED_NET_POSITION"
    assert result["leg_execution_safe"] is False


async def test_divergence_between_legs_and_net_is_flagged(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.4"))
    assert result["status"] == "DIVERGED"
    assert result["computed_net"] == Decimal("1.00000000")
    assert result["difference"] == Decimal("-0.60000000")


async def test_matching_legs_and_net_are_safe_for_hedge_execution(database) -> None:
    service = PositionLegService(database.session_factory)
    await _seed(service, quantity=Decimal("1"))
    await service.apply_order_fill("leg-long", OrderSide.SELL, Decimal("0.25"))
    result = await LegPositionReconciler(service).reconcile("BTCUSDT", Decimal("0.75"))
    assert result["status"] == "MATCHED"
    assert result["leg_execution_safe"] is True
