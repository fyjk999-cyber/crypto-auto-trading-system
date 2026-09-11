"""Core-constraint regression tests for factual external cash-flow valuation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.domain.models import Account, SignalIntent
from crypto_trader.persistence.models import EquitySnapshotORM, LedgerTransactionORM
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.valuation.domain import (
    VALUATION_QUALITY_HEALTHY,
    VALUATION_QUALITY_UNAVAILABLE,
)


async def _cash_flow(
    database,
    *,
    transaction_id: str,
    account_id: str = "A",
    ownership_status: str = "VERIFIED",
    entry_type: str = "DEPOSIT",
    metadata: dict | None = None,
) -> None:
    async with database.session_factory() as session:
        session.add(
            LedgerTransactionORM(
                transaction_id=transaction_id,
                account_id=account_id,
                ownership_status=ownership_status,
                entry_type=entry_type,
                created_at=datetime.now(UTC),
                metadata_json=metadata or {},
            )
        )
        await session.commit()


async def _latest_snapshot(database) -> EquitySnapshotORM:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(EquitySnapshotORM).order_by(EquitySnapshotORM.id.desc()).limit(1)
            )
        ).scalar_one()


async def test_verified_same_scope_deposit_is_applied_factually(database):
    await _cash_flow(
        database,
        transaction_id="dep-usdt",
        metadata={"currency": "USDT", "amount": "100"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_HEALTHY
    assert batch.adjusted_equity == Decimal("900")
    assert batch.drawdown_amount == Decimal("0")
    snap = await _latest_snapshot(database)
    assert snap.cumulative_external_cash_flow == Decimal("100")


async def test_verified_same_scope_withdrawal_is_applied_factually(database):
    await _cash_flow(
        database,
        transaction_id="wd-usdt",
        entry_type="WITHDRAWAL",
        metadata={"currency": "USDT", "amount": "25"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_HEALTHY
    assert batch.adjusted_equity == Decimal("1025")
    snap = await _latest_snapshot(database)
    assert snap.cumulative_external_cash_flow == Decimal("-25")


async def test_other_account_cash_flow_cannot_affect_valuation(database):
    await _cash_flow(
        database,
        transaction_id="dep-account-b",
        account_id="B",
        metadata={"currency": "USDT", "amount": "500"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_HEALTHY
    assert batch.adjusted_equity == Decimal("1000")


async def test_foreign_currency_cash_flow_is_excluded_from_usdt(database):
    await _cash_flow(
        database,
        transaction_id="dep-usdc",
        metadata={"currency": "USDC", "amount": "500"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_HEALTHY
    assert batch.adjusted_equity == Decimal("1000")
    assert not any(
        reason.startswith("CASH_FLOW_") for reason in batch.reason_codes
    )


async def test_missing_cash_flow_currency_makes_valuation_unavailable(database):
    await _cash_flow(
        database,
        transaction_id="dep-no-currency",
        metadata={"amount": "100"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert batch.adjusted_equity is None
    assert batch.drawdown_amount is None
    assert batch.raw_mtm_equity is None
    assert "CASH_FLOW_CURRENCY_UNPROVEN:dep-no-currency" in batch.reason_codes


async def test_missing_amount_is_unknown_not_zero(database):
    await _cash_flow(
        database,
        transaction_id="dep-no-amount",
        metadata={"currency": "USDT"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert batch.adjusted_equity is None
    assert batch.drawdown_amount is None
    assert "CASH_FLOW_AMOUNT_UNPROVEN:dep-no-amount" in batch.reason_codes


async def test_non_finite_amount_is_unknown_not_zero(database):
    await _cash_flow(
        database,
        transaction_id="dep-nan",
        metadata={"currency": "USDT", "amount": "NaN"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert "CASH_FLOW_AMOUNT_UNPROVEN:dep-nan" in batch.reason_codes


async def test_explicit_zero_amount_remains_a_known_fact(database):
    await _cash_flow(
        database,
        transaction_id="dep-zero",
        metadata={"currency": "USDT", "amount": "0"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_HEALTHY
    assert batch.adjusted_equity == Decimal("1000")


async def test_unverified_same_currency_ownership_makes_valuation_unavailable(database):
    await _cash_flow(
        database,
        transaction_id="dep-unverified",
        ownership_status="UNKNOWN",
        metadata={"currency": "USDT", "amount": "100"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert (
        "CASH_FLOW_OWNERSHIP_UNVERIFIED:dep-unverified"
        in batch.reason_codes
    )


async def test_incomplete_cash_flow_does_not_advance_existing_peak(database):
    service = PortfolioService(database.session_factory)
    first = await service.record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert first.peak_adjusted_equity == Decimal("1000")

    await _cash_flow(
        database,
        transaction_id="dep-incomplete",
        metadata={"currency": "USDT"},
    )
    second = await service.record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("9999"),
    )
    assert second.quality == VALUATION_QUALITY_UNAVAILABLE
    assert second.peak_adjusted_equity == Decimal("1000")
    assert second.drawdown_amount is None

    snap = await _latest_snapshot(database)
    assert snap.valuation_status == VALUATION_QUALITY_UNAVAILABLE
    assert snap.peak_adjusted_equity == Decimal("1000")
    assert snap.drawdown is None


def _entry_signal() -> SignalIntent:
    return SignalIntent(
        signal_id="cash-flow-completeness-entry",
        strategy_id="test",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        metadata={"direction": "LONG"},
    )


async def test_incomplete_cash_flow_lineage_fails_closed_for_new_exposure(database):
    await _cash_flow(
        database,
        transaction_id="dep-risk-incomplete",
        metadata={"currency": "USDT"},
    )
    batch = await PortfolioService(database.session_factory).record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    decision = RiskEngine().check(
        _entry_signal(),
        account=Account(account_id="A", equity=Decimal("1000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=batch.drawdown_amount,
        current_equity=batch.adjusted_equity,
        peak_equity=batch.peak_adjusted_equity,
        valuation_id=batch.valuation_id,
        valuation_quality=batch.quality,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason in {"DRAWDOWN_UNAVAILABLE", "VALUATION_UNAVAILABLE"}
    assert decision.checks["valuation_completeness"] == "INCOMPLETE"
