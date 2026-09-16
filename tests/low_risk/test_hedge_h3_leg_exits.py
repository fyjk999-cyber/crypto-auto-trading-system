"""H3 leg-specific deterministic exits (Base Exit per independent leg)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    PositionLegService,
)
from tests.conftest import make_paper_engine

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation over 105",
    base_exit={"type": "PRICE", "trigger": "<=99"},
    invalidation="close below 98",
    evidence_families=["trend"],
    reason="momentum entry",
)

SHORT = HedgeLegContract(
    leg_id="leg-short",
    symbol="BTCUSDT",
    side="SHORT",
    kind=LegKind.HEDGE,
    strategy="MEAN_REVERT",
    thesis="range rejection at 112 with exhaustion",
    base_exit={"type": "PRICE", "trigger": ">=111"},
    invalidation="acceptance above 115",
    evidence_families=["mean_reversion"],
    reason="independent reversal thesis",
)


def _ctx(mark: str):
    return SimpleNamespace(
        mark_price=Decimal(mark),
        book=SimpleNamespace(mid_price=lambda: Decimal(mark)),
        account=SimpleNamespace(equity=Decimal("10000")),
        realized_volatility=0.01,
    )


async def _open_two_legs(database):
    service = PositionLegService(database.session_factory)
    assert (await service.register(LONG)).allowed is True
    assert (await service.register(SHORT)).allowed is True
    await service.allocate_fill(
        fill_id="h3-long-1",
        leg_id="leg-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    await service.allocate_fill(
        fill_id="h3-short-1",
        leg_id="leg-short",
        side="SELL",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    return service


async def test_only_the_leg_whose_base_exit_fires_produces_a_signal(database) -> None:
    await _open_two_legs(database)
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    await engine.start("run-h3-leg-exit")

    signals, wake = await engine._leg_deterministic_exit_signals("BTCUSDT", _ctx("98"))
    leg_ids = [signal.metadata.get("leg_id") for signal, _ in signals]
    assert leg_ids == ["leg-long"]
    signal = signals[0][0]
    assert signal.side.value == "SELL"
    assert signal.metadata["reduce_only"] is True
    assert signal.metadata["deterministic_exit"] is True
    assert signal.metadata["direction"] == "LONG"
    assert signal.quantity <= Decimal("1")
    await engine.stop()


async def test_opposite_leg_is_not_closed_by_the_other_legs_exit(database) -> None:
    service = await _open_two_legs(database)
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    await engine.start("run-h3-leg-exit-2")

    # Mark above the SHORT Base Exit: only the SHORT leg is due.
    signals, _ = await engine._leg_deterministic_exit_signals("BTCUSDT", _ctx("112"))
    assert [signal.metadata.get("leg_id") for signal, _ in signals] == ["leg-short"]
    short_signal = signals[0][0]
    assert short_signal.side.value == "BUY"
    assert short_signal.quantity <= Decimal("1")

    # LONG state is untouched by that evaluation.
    long_state = await service.snapshot_state("leg-long")
    assert long_state["remaining_quantity"] == Decimal("1")
    short_state = await service.snapshot_state("leg-short")
    assert short_state["remaining_quantity"] == Decimal("1")
    await engine.stop()


async def test_closing_one_leg_leaves_only_the_other_leg_protected(database) -> None:
    service = await _open_two_legs(database)
    await service.allocate_fill(
        fill_id="h3-long-close",
        leg_id="leg-long",
        side="SELL",
        price=Decimal("99"),
        quantity=Decimal("1"),
        terminal_reason="BASE_EXIT",
    )
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = PositionLegService(database.session_factory)
    await engine.start("run-h3-leg-exit-3")

    assert (await service.snapshot_state("leg-long"))["state"] == "CLOSED"
    signals, _ = await engine._leg_deterministic_exit_signals("BTCUSDT", _ctx("112"))
    assert [signal.metadata.get("leg_id") for signal, _ in signals] == ["leg-short"]
    assert (await service.snapshot_state("leg-short"))["remaining_quantity"] == Decimal("1")
    await engine.stop()


async def test_leg_exit_quantity_is_capped_to_that_leg_only(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    await service.allocate_fill(
        fill_id="h3-partial",
        leg_id="leg-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("0.4"),
    )
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.leg_service = service
    await engine.start("run-h3-leg-exit-4")
    signals, _ = await engine._leg_deterministic_exit_signals("BTCUSDT", _ctx("98"))
    assert signals, "LONG base exit should be due"
    assert signals[0][0].quantity <= Decimal("0.4")
    assert signals[0][0].metadata["leg_id"] == "leg-long"
    await engine.stop()
