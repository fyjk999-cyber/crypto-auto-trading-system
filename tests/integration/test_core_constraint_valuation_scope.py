"""CORE CONSTRAINT recovery: factual valuation scope + completeness.

Regression proofs for the defects introduced around commit 1d7383d
("persist durable equity peak and feed factual drawdown into risk"):

  A. equity/drawdown history is scoped by account_id + currency — a global
     "latest snapshot" may never feed another account/currency.
  B. an equity value may only update the peak / become a Risk fact when
     complete MTM coverage has been proven (same-symbol factual, fresh,
     healthy approved marks; no omitted position).
  C. unproven/incomplete valuation fails closed for NEW exposure
     (UNKNOWN != ZERO) while legitimate risk-reducing behaviour is kept.
  D. incomplete valuation never advances the peak, and never contaminates
     another scope.
  E. no synthetic/default/cross-symbol price, mark or value is introduced.

No runtime is started by these tests; they use the repository services and
the pure RiskEngine contract only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import (
    ExecutionDecision,
    LedgerDirection,
    LedgerEntryType,
    OrderSide,
)
from crypto_trader.domain.models import Account, Instrument, Position, SignalIntent
from crypto_trader.ledger.service import LedgerPosting, LedgerService
from crypto_trader.persistence.models import EquitySnapshotORM, ValuationBatchORM
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.valuation.domain import (
    VALUATION_QUALITY_HEALTHY,
    VALUATION_QUALITY_UNAVAILABLE,
)
from crypto_trader.valuation.service import ValuationService


def _position(symbol: str = "BTC-USDT-SWAP", quantity: str = "1") -> Position:
    return Position(
        symbol=symbol,
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal(quantity),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("100"),
        instrument_type="LINEAR_PERP",
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )


def _instrument(symbol: str = "BTC-USDT-SWAP") -> Instrument:
    return Instrument(
        symbol=symbol,
        base_asset="BTC",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size="0.01",
        contract_multiplier="1",
    )


def _signal(
    *,
    reduce_only: bool = False,
    side: OrderSide = OrderSide.BUY,
    direction: str | None = None,
) -> SignalIntent:
    metadata = {"direction": direction or ("LONG" if side == OrderSide.BUY else "SHORT")}
    if reduce_only:
        metadata["reduce_only"] = True
    return SignalIntent(
        signal_id="core-constraint-signal",
        strategy_id="test",
        symbol="BTC-USDT-SWAP",
        side=side,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        metadata=metadata,
    )


async def _snapshots(database) -> list[EquitySnapshotORM]:
    async with database.session_factory() as session:
        return list(
            (
                await session.execute(
                    select(EquitySnapshotORM).order_by(EquitySnapshotORM.id)
                )
            ).scalars()
        )


# --------------------------------------------------------------------------
# 1 + 2: scope isolation (account_id and currency)
# --------------------------------------------------------------------------


async def test_account_peak_never_affects_another_account_drawdown(database):
    service = PortfolioService(database.session_factory)
    await service.record_equity_drawdown(
        Decimal("1000"), account_id="A", currency="USDT"
    )
    await service.record_equity_drawdown(
        Decimal("500"), account_id="A", currency="USDT"
    )
    # Account B starts its own history: A's peak (1000) must be invisible.
    drawdown_b, peak_b, _, _ = await service.record_equity_drawdown(
        Decimal("100"), account_id="B", currency="USDT"
    )
    assert peak_b == Decimal("100")
    assert drawdown_b == Decimal("0")

    drawdown_a, peak_a, _, _ = await service.record_equity_drawdown(
        Decimal("900"), account_id="A", currency="USDT"
    )
    assert peak_a == Decimal("1000")
    assert drawdown_a == Decimal("-100")
    # B remains untouched by A's later valuation.
    drawdown_b2, peak_b2, _, _ = await service.record_equity_drawdown(
        Decimal("90"), account_id="B", currency="USDT"
    )
    assert peak_b2 == Decimal("100")
    assert drawdown_b2 == Decimal("-10")

    scopes = {(row.account_id, row.currency) for row in await _snapshots(database)}
    assert scopes == {("A", "USDT"), ("B", "USDT")}


async def test_currency_scope_is_isolated_from_usdt_history(database):
    service = PortfolioService(database.session_factory)
    await service.record_equity_drawdown(
        Decimal("1000"), account_id="A", currency="USDT"
    )
    # Same account, different currency: USDT peak must not leak in.
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("10"), account_id="A", currency="USDC"
    )
    assert peak == Decimal("10")
    assert drawdown == Decimal("0")

    # And a later USDC drop only refers to the USDC peak.
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("8"), account_id="A", currency="USDC"
    )
    assert peak == Decimal("10")
    assert drawdown == Decimal("-2")

    # USDT history is unaffected by the USDC valuations.
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("950"), account_id="A", currency="USDT"
    )
    assert peak == Decimal("1000")
    assert drawdown == Decimal("-50")


# --------------------------------------------------------------------------
# 3 + 4: peak advances only from complete, same-scope valuations
# --------------------------------------------------------------------------


async def test_complete_valuation_advances_same_scope_peak_only(database):
    service = PortfolioService(database.session_factory)
    await service.record_equity_drawdown(Decimal("100"), account_id="A", currency="USDT")
    await service.record_equity_drawdown(Decimal("150"), account_id="A", currency="USDT")
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("150"), account_id="B", currency="USDT"
    )
    assert peak == Decimal("150")  # B's own peak, not A's higher history
    assert drawdown == Decimal("0")

    drawdown_a, peak_a, _, _ = await service.record_equity_drawdown(
        Decimal("300"), account_id="A", currency="USDT"
    )
    assert peak_a == Decimal("300")
    assert drawdown_a == Decimal("0")


async def test_incomplete_valuation_never_advances_peak(database):
    service = PortfolioService(database.session_factory)
    await service.record_equity_drawdown(Decimal("100"), account_id="A", currency="USDT")
    # A huge but INCOMPLETE valuation must not raise the peak.
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("999999"),
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_UNAVAILABLE,
        reason_codes=["VALUATION_UNAVAILABLE"],
        missing_marks=["ETH-USDT-SWAP"],
    )
    assert drawdown is None
    assert peak == Decimal("100")  # unchanged from the last complete fact

    rows = await _snapshots(database)
    latest = rows[-1]
    assert latest.valuation_status == VALUATION_QUALITY_UNAVAILABLE
    assert latest.drawdown is None
    assert latest.peak_adjusted_equity == Decimal("100")


# --------------------------------------------------------------------------
# 5 + 6 + 7 + 10: valuation completeness proofs (no synthetic facts)
# --------------------------------------------------------------------------


async def test_missing_required_mark_is_unavailable_not_zero(database):
    service = PortfolioService(database.session_factory)
    valuations = ValuationService(portfolio=service, ledger=_StubLedger())
    batch = await valuations.build(
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position()},
        market_prices={},  # required same-symbol mark missing
        instruments={"BTC-USDT-SWAP": _instrument()},
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert batch.raw_mtm_equity is None  # never zero, never the entry price
    assert batch.usable_for_new_risk is False
    assert batch.missing_marks == ("BTC-USDT-SWAP",)
    assert "MISSING_MARKS" in batch.reason_codes
    assert batch.components == ()  # no fabricated component valuation


async def test_stale_or_unhealthy_mark_cannot_be_complete(database):
    service = PortfolioService(database.session_factory)
    valuations = ValuationService(portfolio=service, ledger=_StubLedger())
    stale = await valuations.build(
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position()},
        market_prices={"BTC-USDT-SWAP": Decimal("100")},
        instruments={"BTC-USDT-SWAP": _instrument()},
        is_fresh=lambda _symbol: False,  # stale book
        require_mark_healthy=lambda _symbol: True,
    )
    assert stale.quality == VALUATION_QUALITY_UNAVAILABLE
    assert stale.raw_mtm_equity is None
    assert "BTC-USDT-SWAP" in stale.stale_marks
    assert "STALE_MARKS" in stale.reason_codes

    unhealthy = await valuations.build(
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position()},
        market_prices={"BTC-USDT-SWAP": Decimal("100")},
        instruments={"BTC-USDT-SWAP": _instrument()},
        is_fresh=lambda _symbol: True,
        require_mark_healthy=lambda _symbol: False,  # unhealthy book
    )
    assert unhealthy.quality == VALUATION_QUALITY_UNAVAILABLE
    assert unhealthy.raw_mtm_equity is None
    assert "BTC-USDT-SWAP" in unhealthy.stale_marks
    assert "MARK_BOOK_UNHEALTHY:BTC-USDT-SWAP" in unhealthy.reason_codes


async def test_wrong_symbol_mark_cannot_satisfy_completeness(database):
    service = PortfolioService(database.session_factory)
    valuations = ValuationService(portfolio=service, ledger=_StubLedger())
    # Only a DIFFERENT symbol's mark exists: the held position stays uncovered.
    cross_symbol = await valuations.build(
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position()},
        market_prices={"ETH-USDT-SWAP": Decimal("2500")},
        instruments={
            "BTC-USDT-SWAP": _instrument(),
            "ETH-USDT-SWAP": _instrument("ETH-USDT-SWAP"),
        },
    )
    assert cross_symbol.quality == VALUATION_QUALITY_UNAVAILABLE
    assert cross_symbol.raw_mtm_equity is None
    assert cross_symbol.missing_marks == ("BTC-USDT-SWAP",)
    assert all(
        component["instrument_id"] != "ETH-USDT-SWAP"
        for component in cross_symbol.components
    )

    # A mark whose product metadata does not match the position is not usable.
    product_mismatch = await valuations.build(
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position()},
        market_prices={"BTC-USDT-SWAP": Decimal("100")},
        instruments={
            "BTC-USDT-SWAP": Instrument(
                symbol="BTC-USDT-SWAP",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type="SPOT",
            )
        },
    )
    assert product_mismatch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert product_mismatch.raw_mtm_equity is None
    assert "INSTRUMENT_PRODUCT_MISMATCH:BTC-USDT-SWAP" in product_mismatch.reason_codes


async def test_complete_marks_produce_the_only_factual_value(database):
    service = PortfolioService(database.session_factory)
    valuations = ValuationService(portfolio=service, ledger=_StubLedger())
    batch = await valuations.build(
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position(quantity="1")},
        market_prices={"BTC-USDT-SWAP": Decimal("110")},
        instruments={"BTC-USDT-SWAP": _instrument()},
    )
    assert batch.quality == VALUATION_QUALITY_HEALTHY
    # 10000 + (110-100) * 1 * 0.01 * 1 = 10000.1 — derived only from the
    # factual same-symbol mark, never from a synthetic/default price.
    assert batch.raw_mtm_equity == Decimal("10000.10")
    assert batch.usable_for_new_risk is True
    assert batch.components[0]["mark_price"] == "110"
    assert batch.components[0]["price_source"] == "ORDERBOOK_MID"


async def test_incomplete_valuation_persists_without_peak_or_drawdown(database):
    """The canonical write path stores the incompleteness, not a fake value."""
    service = PortfolioService(database.session_factory)
    batch = await service.record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_UNAVAILABLE,
        fallback_equity=Decimal("12345"),
        missing_marks=["BTC-USDT-SWAP"],
        reason_codes=["MISSING_MARKS"],
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert batch.raw_mtm_equity is None  # the fallback is not a factual MTM value
    assert batch.peak_adjusted_equity is None
    assert batch.drawdown_amount is None
    assert batch.usable_for_new_risk is False
    async with database.session_factory() as session:
        stored = (
            await session.execute(select(ValuationBatchORM))
        ).scalar_one()
    assert stored.quality == VALUATION_QUALITY_UNAVAILABLE
    assert stored.raw_mtm_equity is None
    assert stored.peak_adjusted_equity is None
    assert stored.drawdown_amount is None


# --------------------------------------------------------------------------
# 8 + 9: Risk fails closed on unproven valuation, keeps reduction semantics
# --------------------------------------------------------------------------


def test_new_exposure_fails_closed_without_proven_valuation():
    engine = RiskEngine()
    account = Account(equity=Decimal("10000"))

    # No valuation context at all: unknown, not zero.
    decision = engine.check(
        _signal(),
        account=account,
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "DRAWDOWN_UNAVAILABLE"
    assert decision.checks["drawdown"] is None
    assert decision.checks["valuation_completeness"] == "INCOMPLETE"
    assert decision.checks["valuation_proven"] is False

    # Drawdown supplied, but the valuation is explicitly UNAVAILABLE.
    unavailable = engine.check(
        _signal(),
        account=account,
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        valuation_id="val-unavailable",
        valuation_quality=VALUATION_QUALITY_UNAVAILABLE,
    )
    assert unavailable.decision == ExecutionDecision.REJECT
    assert unavailable.reason == "VALUATION_UNAVAILABLE"
    assert unavailable.checks["current_equity"] is None

    # A quality claim without a referenceable batch is not proof either.
    unproven_lineage = engine.check(
        _signal(),
        account=account,
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        valuation_quality=VALUATION_QUALITY_HEALTHY,
    )
    assert unproven_lineage.decision == ExecutionDecision.REJECT
    assert unproven_lineage.reason == "VALUATION_LINEAGE_UNPROVEN"


def test_unproven_equity_is_not_recorded_as_a_factual_check():
    engine = RiskEngine()
    decision = engine.check(
        _signal(),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        current_equity=Decimal("10000"),  # ledger fallback, unproven
        peak_equity=Decimal("10000"),
        valuation_id="val-unavailable",
        valuation_quality=VALUATION_QUALITY_UNAVAILABLE,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.checks["current_equity"] is None
    assert decision.checks["peak_equity"] is None
    assert decision.checks["drawdown"] is None
    assert decision.checks["risk_equity"] is None
    assert decision.checks["valuation_completeness"] == "INCOMPLETE"


def test_proven_valuation_authorizes_new_exposure_with_referenceable_facts():
    engine = RiskEngine()
    decision = engine.check(
        _signal(),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        current_equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        valuation_id="val-complete",
        valuation_quality=VALUATION_QUALITY_HEALTHY,
    )
    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks["valuation_proven"] is True
    assert decision.checks["valuation_completeness"] == "COMPLETE"
    assert decision.checks["valuation_id"] == "val-complete"
    assert decision.checks["current_equity"] == "10000"
    assert decision.checks["risk_equity"] == "10000"


def test_max_drawdown_limit_still_applies_to_proven_valuation():
    engine = RiskEngine()
    decision = engine.check(
        _signal(),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=-Decimal("300000"),
        valuation_id="val-complete",
        valuation_quality=VALUATION_QUALITY_HEALTHY,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_DRAWDOWN"


def test_risk_reducing_action_keeps_approved_semantics_without_valuation():
    engine = RiskEngine()
    position = _position(quantity="2")
    decision = engine.check(
        _signal(reduce_only=True, side=OrderSide.SELL, direction="LONG"),
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=None,  # unknown accounting
        drawdown=None,  # unknown drawdown
    )
    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks["reduce_only"] is True
    assert decision.checks["drawdown_unavailable"] is True
    assert decision.checks["valuation_completeness"] == "INCOMPLETE"


def test_unproven_valuation_never_authorizes_a_reversal():
    """An incomplete valuation must not sneak a hidden direction reversal in."""
    engine = RiskEngine()
    position = _position(quantity="1")
    decision = engine.check(
        _signal(reduce_only=True, side=OrderSide.BUY),  # would grow the LONG
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        drawdown=None,
        daily_pnl=None,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "REDUCE_ONLY_DIRECTION_REVERSAL"


class _StubLedger:
    """Factual ledger seam for ValuationService (no I/O, no synthetic data)."""

    async def watermark(self, *, account_id: str, currency: str) -> str:
        return f"watermark:{account_id}:{currency}"


def test_future_mark_timestamp_is_not_complete(database):
    """A mark timestamped in the future is not a usable factual mark."""
    import asyncio

    service = PortfolioService(database.session_factory)
    valuations = ValuationService(portfolio=service, ledger=_StubLedger())
    future = datetime.now(UTC) + timedelta(minutes=5)
    batch = asyncio.run(
        valuations.build(
            account=Account(equity=Decimal("10000")),
            positions={"BTC-USDT-SWAP": _position()},
            market_prices={"BTC-USDT-SWAP": Decimal("100")},
            instruments={"BTC-USDT-SWAP": _instrument()},
            mark_timestamps={"BTC-USDT-SWAP": future},
            allowed_future_skew_seconds=0,
        )
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert batch.raw_mtm_equity is None
    assert "FUTURE_MARK_TIMESTAMP:BTC-USDT-SWAP" in batch.reason_codes


# --------------------------------------------------------------------------
# FOLLOW-UP: external cash-flow currency scope (no implicit valuation-currency
# fallback). A transaction's own PROVEN currency decides its scope; an
# unprovable currency makes the valuation's cash-flow completeness INCOMPLETE.
# --------------------------------------------------------------------------


async def _record_flow(
    database,
    *,
    transaction_id: str,
    entry_type: LedgerEntryType = LedgerEntryType.DEPOSIT,
    account_id: str = "A",
    amount: str | None = "100",
    currency: str | None = "USDT",
) -> None:
    """Write one VERIFIED external flow, optionally WITHOUT a proven currency."""
    metadata: dict[str, str] = {}
    if amount is not None:
        metadata["amount"] = amount
    if currency is not None:
        metadata["currency"] = currency
    if entry_type == LedgerEntryType.DEPOSIT:
        postings = [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal(amount or "0")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal(amount or "0")),
        ]
    else:
        postings = [
            LedgerPosting("CASH", LedgerDirection.CREDIT, Decimal(amount or "0")),
            LedgerPosting("EQUITY", LedgerDirection.DEBIT, Decimal(amount or "0")),
        ]
    await LedgerService(database.session_factory).record(
        entry_type,
        postings,
        transaction_id=transaction_id,
        account_id=account_id,
        metadata=metadata,
    )


async def _latest_snapshot(database, *, account_id: str = "A", currency: str = "USDT"):
    async with database.session_factory() as session:
        rows = (
            await session.execute(
                select(EquitySnapshotORM)
                .where(
                    EquitySnapshotORM.account_id == account_id,
                    EquitySnapshotORM.currency == currency,
                )
                .order_by(EquitySnapshotORM.id)
            )
        ).scalars().all()
    return rows[-1] if rows else None


async def test_missing_flow_currency_is_never_attributed_to_valuation_currency(database):
    """1: an unproven transaction currency is not silently read as USDT."""
    await _record_flow(
        database, transaction_id="txn_no_currency", amount="500", currency=None
    )
    service = PortfolioService(database.session_factory)
    batch = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    # The 500 was NOT attributed to this USDT scope ...
    snapshot = await _latest_snapshot(database)
    assert snapshot.cumulative_external_cash_flow == Decimal("0")
    assert snapshot.external_cash_flow_adjustment == Decimal("0")
    # ... and the unprovable scope makes the valuation incomplete instead.
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert "CASH_FLOW_CURRENCY_UNPROVEN" in batch.reason_codes
    assert batch.adjusted_equity is None
    assert batch.usable_for_new_risk is False


async def test_foreign_currency_flow_cannot_affect_usdt_scope(database):
    """2: a PROVEN foreign-currency flow stays out of the USDT peak/equity."""
    await _record_flow(
        database, transaction_id="txn_usdc", amount="500", currency="USDC"
    )
    service = PortfolioService(database.session_factory)

    usdt = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert usdt.quality == VALUATION_QUALITY_HEALTHY
    assert usdt.adjusted_equity == Decimal("1000")  # USDC flow excluded
    assert usdt.peak_adjusted_equity == Decimal("1000")
    assert usdt.drawdown_amount == Decimal("0")
    usdt_snapshot = await _latest_snapshot(database, currency="USDT")
    assert usdt_snapshot.cumulative_external_cash_flow == Decimal("0")

    # The same flow IS the factual cash flow of its own USDC scope.
    usdc = await service.record_valuation_batch(
        account_id="A", currency="USDC", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert usdc.quality == VALUATION_QUALITY_HEALTHY
    assert usdc.adjusted_equity == Decimal("500")
    assert usdc.peak_adjusted_equity == Decimal("500")
    usdc_snapshot = await _latest_snapshot(database, currency="USDC")
    assert usdc_snapshot.cumulative_external_cash_flow == Decimal("500")


async def test_proven_same_scope_cash_flow_is_applied_normally(database):
    """3: same-account + same-currency proven flows work as before."""
    await _record_flow(
        database, transaction_id="txn_deposit_usdt", amount="200", currency="USDT"
    )
    service = PortfolioService(database.session_factory)
    deposit = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert deposit.quality == VALUATION_QUALITY_HEALTHY
    assert deposit.adjusted_equity == Decimal("800")  # 1000 - 200 deposit
    assert deposit.peak_adjusted_equity == Decimal("800")
    assert deposit.drawdown_amount == Decimal("0")
    snapshot = await _latest_snapshot(database)
    assert snapshot.cumulative_external_cash_flow == Decimal("200")
    assert snapshot.cash_flow_adjusted_equity == Decimal("800")

    await _record_flow(
        database,
        transaction_id="txn_withdrawal_usdt",
        entry_type=LedgerEntryType.WITHDRAWAL,
        amount="300",
        currency="USDT",
    )
    withdrawal = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    # 1000 - (200 deposit - 300 withdrawal) = 1100 adjusted equity
    assert withdrawal.adjusted_equity == Decimal("1100")
    assert withdrawal.peak_adjusted_equity == Decimal("1100")
    assert withdrawal.reason_codes == ()


async def test_unproven_flow_currency_makes_valuation_incomplete(database):
    """4: claimed HEALTHY is downgraded using the existing quality/reason codes."""
    await _record_flow(
        database, transaction_id="txn_unproven_currency", amount="500", currency=None
    )
    service = PortfolioService(database.session_factory)
    batch = await service.record_valuation_batch(
        account_id="A",
        currency="USDT",
        quality=VALUATION_QUALITY_HEALTHY,  # caller's claim
        raw_mtm_equity=Decimal("12345"),
        reason_codes=["MARK_PROVEN"],
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert "CASH_FLOW_CURRENCY_UNPROVEN" in batch.reason_codes
    assert "MARK_PROVEN" in batch.reason_codes  # caller facts preserved
    assert batch.raw_mtm_equity is None
    assert batch.adjusted_equity is None
    assert batch.peak_adjusted_equity is None
    assert batch.drawdown_amount is None
    assert batch.drawdown_ratio is None
    assert batch.solvency is None
    assert batch.usable_for_new_risk is False
    snapshot = await _latest_snapshot(database)
    assert snapshot.valuation_status == VALUATION_QUALITY_UNAVAILABLE
    assert snapshot.drawdown is None
    assert snapshot.peak_adjusted_equity is None
    async with database.session_factory() as session:
        stored = (await session.execute(select(ValuationBatchORM))).scalar_one()
    assert stored.quality == VALUATION_QUALITY_UNAVAILABLE
    assert "CASH_FLOW_CURRENCY_UNPROVEN" in stored.reason_codes_json


async def test_missing_flow_amount_is_not_treated_as_zero_cash_flow(database):
    """Adjacent hole of the same invariant: UNKNOWN amount != zero flow."""
    await _record_flow(
        database,
        transaction_id="txn_no_amount",
        amount=None,  # currency proven, amount unprovable
        currency="USDT",
    )
    service = PortfolioService(database.session_factory)
    batch = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE
    assert "CASH_FLOW_AMOUNT_UNPROVEN" in batch.reason_codes
    assert batch.adjusted_equity is None
    snapshot = await _latest_snapshot(database)
    assert snapshot.cumulative_external_cash_flow == Decimal("0")


async def test_incomplete_cash_flow_scope_cannot_advance_peak(database):
    """5: an unprovable cash-flow scope never moves the historical peak."""
    service = PortfolioService(database.session_factory)
    baseline = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("1000"),
    )
    assert baseline.peak_adjusted_equity == Decimal("1000")

    await _record_flow(
        database, transaction_id="txn_later_unproven", amount="500", currency=None
    )
    incomplete = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("5000"),
    )
    assert incomplete.quality == VALUATION_QUALITY_UNAVAILABLE
    assert incomplete.peak_adjusted_equity == Decimal("1000")  # unchanged
    assert incomplete.drawdown_amount is None
    snapshot = await _latest_snapshot(database)
    assert snapshot.peak_adjusted_equity == Decimal("1000")
    assert snapshot.drawdown is None
    assert snapshot.valuation_status == VALUATION_QUALITY_UNAVAILABLE


async def test_incomplete_cash_flow_scope_fails_closed_for_new_exposure(database):
    """6: the incomplete batch cannot authorize new exposure through Risk."""
    await _record_flow(
        database, transaction_id="txn_unproven_exposure", amount="500", currency=None
    )
    service = PortfolioService(database.session_factory)
    batch = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("10000"),
    )
    assert batch.usable_for_new_risk is False

    decision = RiskEngine().check(
        _signal(),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=batch.drawdown_amount,  # None — unknown, not zero
        valuation_id=batch.valuation_id,
        valuation_quality=batch.quality,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "DRAWDOWN_UNAVAILABLE"  # unknown, never zero
    assert decision.checks["drawdown"] is None
    assert decision.checks["valuation_completeness"] == "INCOMPLETE"
    assert decision.checks["valuation_quality"] == VALUATION_QUALITY_UNAVAILABLE

    # Even if a (wrong) zero drawdown is supplied, the incomplete valuation
    # itself still blocks new exposure: UNKNOWN cannot be bought with 0.
    forged = RiskEngine().check(
        _signal(),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        valuation_id=batch.valuation_id,
        valuation_quality=batch.quality,
    )
    assert forged.decision == ExecutionDecision.REJECT
    assert forged.reason == "VALUATION_UNAVAILABLE"
    assert forged.checks["valuation_completeness"] == "INCOMPLETE"


async def test_incomplete_cash_flow_scope_still_allows_reduce_only(database):
    """7: risk-reducing lifecycle behaviour is preserved."""
    await _record_flow(
        database, transaction_id="txn_unproven_reduction", amount="500", currency=None
    )
    service = PortfolioService(database.session_factory)
    batch = await service.record_valuation_batch(
        account_id="A", currency="USDT", quality=VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity=Decimal("10000"),
    )
    assert batch.quality == VALUATION_QUALITY_UNAVAILABLE

    decision = RiskEngine().check(
        _signal(reduce_only=True, side=OrderSide.SELL, direction="LONG"),
        account=Account(equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": _position(quantity="2")},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=None,
        drawdown=batch.drawdown_amount,
        valuation_id=batch.valuation_id,
        valuation_quality=batch.quality,
    )
    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks["reduce_only"] is True
    assert decision.checks["valuation_completeness"] == "INCOMPLETE"
