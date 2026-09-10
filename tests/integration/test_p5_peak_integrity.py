"""P5: valuation quality and solvency are independent; unavailable never peaks."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from crypto_trader.persistence.models import EquitySnapshotORM, ValuationBatchORM
from crypto_trader.portfolio.service import PortfolioService


async def _latest_snapshot(database):
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(EquitySnapshotORM).order_by(EquitySnapshotORM.id.desc()).limit(1)
            )
        ).scalar_one()


async def test_positive_solvency_unavailable_quality_is_legal_and_null_peak(database):
    service = PortfolioService(database.session_factory)
    assert PortfolioService.classify_equity_status(Decimal("100")) == "HEALTHY"
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("100"),
        quality="UNAVAILABLE",
        reason_codes=["VALUATION_UNAVAILABLE"],
        missing_marks=["BTC-USDT-SWAP"],
    )
    assert drawdown is None and peak is None
    snapshot = await _latest_snapshot(database)
    # Solvency is positive (book equity > 0) but valuation quality is
    # UNAVAILABLE. Neither field may substitute for the other.
    assert snapshot.current_equity == Decimal("100")
    assert snapshot.valuation_status == "UNAVAILABLE"
    assert snapshot.peak_adjusted_equity is None
    assert snapshot.drawdown is None
    async with database.session_factory() as session:
        batch = (await session.execute(select(ValuationBatchORM))).scalar_one()
    assert batch.quality == "UNAVAILABLE"
    assert batch.peak_adjusted_equity is None
    assert batch.drawdown_amount is None
    assert batch.drawdown_ratio is None


async def test_first_healthy_valuation_is_the_only_baseline(database):
    service = PortfolioService(database.session_factory)
    # Unavailable first must not create a numeric baseline.
    await service.record_equity_drawdown(
        Decimal("500"), quality="UNAVAILABLE", reason_codes=["VALUATION_UNAVAILABLE"]
    )
    # Next unavailable still cannot create one.
    await service.record_equity_drawdown(
        Decimal("900"), quality="UNAVAILABLE", reason_codes=["VALUATION_UNAVAILABLE"]
    )
    snapshot = await _latest_snapshot(database)
    assert snapshot.peak_adjusted_equity is None
    # First HEALTHY establishes the baseline from adjusted equity.
    drawdown, peak, _, _ = await service.record_equity_drawdown(Decimal("700"))
    assert peak == Decimal("700")
    assert drawdown == Decimal("0")
    # Later unavailable cannot move it.
    await service.record_equity_drawdown(
        Decimal("9000"), quality="UNAVAILABLE", reason_codes=["VALUATION_UNAVAILABLE"]
    )
    snapshot = await _latest_snapshot(database)
    assert snapshot.peak_adjusted_equity == Decimal("700")
    assert snapshot.drawdown is None
    assert snapshot.valuation_status == "UNAVAILABLE"
