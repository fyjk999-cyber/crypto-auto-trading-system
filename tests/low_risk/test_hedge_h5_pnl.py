"""H5 leg economics and aggregation-proof tests (HEDGE final closure)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    LegKind,
    PositionLegService,
    compare_leg_symbol_to_portfolio,
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


async def test_leg_economics_mark_to_market_fees_and_net(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    await service.allocate_fill(
        fill_id="h5-l1",
        leg_id="leg-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
        fee=Decimal("0.05"),
    )
    economics = await service.leg_economics("leg-long", mark_price=Decimal("110"))
    assert economics["average_entry_price"] == Decimal("100")
    assert economics["unrealized_pnl"] == Decimal("10")
    assert economics["gross_pnl"] == Decimal("10")
    assert economics["fees"] == Decimal("0.05")
    assert economics["net_pnl"] == Decimal("9.95")
    assert economics["is_order"] is False


async def test_symbol_economics_is_exact_sum_of_independent_legs(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    await service.register(SHORT)
    await service.allocate_fill(
        fill_id="h5-s-l",
        leg_id="leg-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
        fee=Decimal("0.1"),
    )
    await service.allocate_fill(
        fill_id="h5-s-s",
        leg_id="leg-short",
        side="SELL",
        price=Decimal("102"),
        quantity=Decimal("1"),
        fee=Decimal("0.2"),
    )
    report = await service.symbol_economics("BTCUSDT", mark_price=Decimal("101"))
    assert report["net_quantity"] == Decimal("0")
    assert report["gross_quantity"] == Decimal("2")
    assert report["both_sides"] is True
    assert report["netting_hides_gross"] is True
    assert report["unrealized_pnl"] == Decimal("2")
    assert report["fees"] == Decimal("0.3")
    assert report["net_pnl"] == Decimal("1.7")
    legs_sum = sum((leg["net_pnl"] for leg in report["legs"]), Decimal("0"))
    assert legs_sum == report["net_pnl"]


async def test_net_zero_symbol_to_portfolio_requires_gross_view(database) -> None:
    service = PositionLegService(database.session_factory)
    await service.register(LONG)
    await service.register(SHORT)
    await service.allocate_fill(
        fill_id="h5-nz-l",
        leg_id="leg-long",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("1"),
    )
    await service.allocate_fill(
        fill_id="h5-nz-s",
        leg_id="leg-short",
        side="SELL",
        price=Decimal("102"),
        quantity=Decimal("1"),
    )
    report = await service.symbol_economics("BTCUSDT", mark_price=Decimal("101"))
    fake_net_position = SimpleNamespace(
        quantity=Decimal("0"), unrealized_pnl=Decimal("0"), realized_pnl=Decimal("0")
    )
    comparison = compare_leg_symbol_to_portfolio(report, fake_net_position)
    assert comparison["status"] == "GROSS_VIEW_REQUIRED"
    assert comparison["match"] is False
    assert comparison["leg_gross_pnl"] == Decimal("2")
    assert comparison["portfolio_unrealized_pnl"] == Decimal("0")


async def test_single_side_leg_matches_real_paper_portfolio(database) -> None:
    from tests.low_risk.test_phase4_runtime_deterministic_exit import _open_v2_position

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    try:
        await engine.start("run-h5-pnl")
        assert await engine._strategy_context("BTCUSDT") is not None
        await _open_v2_position(engine, database)
        await engine.wait_for_event_queue()
        position = await engine.portfolio.get_position("BTCUSDT")
        assert position is not None and position.quantity > 0

        service = PositionLegService(database.session_factory)
        await service.register(LONG)
        avg = Decimal(str(position.avg_entry_price))
        mark = Decimal(str(getattr(position, "mark_price", None) or avg))
        await service.allocate_fill(
            fill_id="h5-portfolio-leg",
            leg_id="leg-long",
            side="BUY",
            price=avg,
            quantity=Decimal(str(position.quantity)),
        )
        report = await service.symbol_economics("BTCUSDT", mark_price=mark)
        comparison = compare_leg_symbol_to_portfolio(report, position)
        assert comparison["status"] == "MATCH", comparison
        assert abs(comparison["unrealized_difference"]) <= Decimal("0.00000001")
        assert abs(comparison["realized_difference"]) <= Decimal("0.00000001")
    finally:
        await engine.stop()
