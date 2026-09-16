"""H1 canonical leg accounting tests (HEDGE final closure)."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    PositionLegService,
)

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation over 105",
    base_exit={"type": "PRICE", "trigger": ">=110"},
    invalidation="close below 98",
    evidence_families=["trend", "orderflow"],
    reason="momentum entry",
)

SHORT_HEDGE = HedgeLegContract(
    leg_id="leg-short",
    symbol="BTCUSDT",
    side="SHORT",
    kind=LegKind.HEDGE,
    strategy="MEAN_REVERT",
    thesis="range rejection at 112 with exhaustion",
    base_exit={"type": "PRICE", "trigger": "<=104"},
    invalidation="acceptance above 115",
    evidence_families=["mean_reversion", "orderbook"],
    reason="independent reversal thesis",
)


async def test_long_leg_vwap_realized_pnl_and_terminal_close(database) -> None:
    service = PositionLegService(database.session_factory)
    assert (await service.register(LONG)).allowed is True

    await service.apply_fill(
        "leg-long", Decimal("1"), price=Decimal("100"), fee=Decimal("0.1"), fill_id="f1"
    )
    await service.apply_fill("leg-long", Decimal("1"), price=Decimal("110"), fill_id="f2")

    opened = await service.snapshot_state("leg-long")
    assert opened["quantity"] == Decimal("2")
    assert opened["remaining_quantity"] == Decimal("2")
    assert opened["average_entry_price"] == Decimal("105")

    await service.apply_fill(
        "leg-long", Decimal("-0.5"), price=Decimal("120"), fee=Decimal("0.05"), fill_id="f3"
    )
    partial = await service.snapshot_state("leg-long")
    assert partial["remaining_quantity"] == Decimal("1.5")
    assert partial["closed_quantity"] == Decimal("0.5")
    assert partial["realized_pnl"] == Decimal("7.5")
    assert partial["exit_vwap"] == Decimal("120")
    assert partial["fees"] == Decimal("0.15")
    assert partial["net_pnl"] == Decimal("7.35")
    assert partial["state"] == "OPEN"

    await service.apply_fill(
        "leg-long", Decimal("-1.5"), price=Decimal("90"), fill_id="f4", terminal_reason="BASE_EXIT"
    )
    closed = await service.snapshot_state("leg-long")
    assert closed["remaining_quantity"] == Decimal("0")
    assert closed["closed_quantity"] == Decimal("2")
    assert closed["realized_pnl"] == Decimal("-15")
    assert closed["exit_vwap"] == Decimal("97.5")
    assert closed["state"] == "CLOSED"
    assert closed["terminal_reason"] == "BASE_EXIT"
    assert closed["authority"] == "POSITION_LEG_TRUTH"
    assert closed["is_order"] is False


async def test_short_leg_is_mirrored_and_partial(database) -> None:
    service = PositionLegService(database.session_factory)
    assert (await service.register(SHORT_HEDGE)).allowed is True

    await service.apply_fill("leg-short", Decimal("2"), price=Decimal("100"), fill_id="s1")
    await service.apply_fill("leg-short", Decimal("-1"), price=Decimal("90"), fill_id="s2")
    partial = await service.snapshot_state("leg-short")
    assert partial["remaining_quantity"] == Decimal("1")
    assert partial["realized_pnl"] == Decimal("10")

    await service.apply_fill("leg-short", Decimal("-1"), price=Decimal("105"), fill_id="s3")
    closed = await service.snapshot_state("leg-short")
    assert closed["remaining_quantity"] == Decimal("0")
    assert closed["realized_pnl"] == Decimal("5")
    assert closed["exit_vwap"] == Decimal("97.5")
    assert closed["state"] == "CLOSED"


async def test_duplicate_fill_id_is_idempotent(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    await service.apply_fill("leg-long", Decimal("1"), price=Decimal("100"), fill_id="dup-1")
    await service.apply_fill("leg-long", Decimal("1"), price=Decimal("100"), fill_id="dup-1")
    state = await service.snapshot_state("leg-long")
    assert state["remaining_quantity"] == Decimal("1")
    assert state["quantity"] == Decimal("1")


async def test_close_one_leg_does_not_touch_the_other(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    await service.register(SHORT_HEDGE)

    await service.apply_order_fill("leg-long", OrderSide.BUY, Decimal("1"), price=Decimal("100"))
    await service.apply_order_fill("leg-short", OrderSide.SELL, Decimal("1"), price=Decimal("102"))
    assert (await service.snapshot_state("leg-short"))["remaining_quantity"] == Decimal("1")

    # Close LONG only; the independent SHORT leg must remain open with its basis.
    await service.apply_order_fill(
        "leg-long", OrderSide.SELL, Decimal("1"), price=Decimal("99"), terminal_reason="EXIT"
    )
    long_state = await service.snapshot_state("leg-long")
    short_state = await service.snapshot_state("leg-short")
    assert long_state["state"] == "CLOSED" and long_state["remaining_quantity"] == Decimal("0")
    assert short_state["state"] == "OPEN" and short_state["remaining_quantity"] == Decimal("1")
    assert short_state["average_entry_price"] == Decimal("102")

    exposure = await service.gross_exposure("BTCUSDT")
    assert exposure["long"] == Decimal("0")
    assert exposure["short"] == Decimal("1")
    assert exposure["net"] == Decimal("-1")
    assert exposure["gross"] == Decimal("1")
