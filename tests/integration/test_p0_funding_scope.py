"""P0 acceptance: funding/PnL must never cross account/currency/instrument."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.domain.enums import (
    ExecutionDecision,
    LedgerDirection,
    LedgerEntryType,
    OrderSide,
)
from crypto_trader.domain.models import Account, Position, SignalIntent
from crypto_trader.ledger.service import (
    FundingScope,
    FundingStatus,
    LedgerPosting,
    LedgerService,
)
from crypto_trader.perpetual.funding_settlement import compute_paper_funding
from crypto_trader.persistence.models import LedgerEntryORM, LedgerTransactionORM
from crypto_trader.risk.engine import RiskEngine

WINDOW_START = datetime(2026, 9, 10, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 10, 8, tzinfo=UTC)


@pytest.fixture
def ledger(database):
    return LedgerService(database.session_factory)


async def _settle(
    ledger,
    *,
    account_id="default",
    currency="USDT",
    instrument_id="BTC-USDT-SWAP",
    quantity="-1",
    rate="0.001",
    hour=4,
):
    settlement = compute_paper_funding(
        settlement_timestamp=datetime(2026, 9, 10, hour, tzinfo=UTC),
        signed_quantity=Decimal(quantity),
        mark_price=Decimal("100"),
        funding_rate=Decimal(rate),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        currency=currency,
        account_id=account_id,
        instrument_id=instrument_id,
    )
    return await ledger.apply_paper_funding_settlement(settlement)


def test_funding_scope_requires_all_five_dimensions():
    with pytest.raises(ValueError):
        FundingScope(
            account_id="",
            currency="USDT",
            instrument_id="BTC-USDT-SWAP",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
    with pytest.raises(ValueError):
        FundingScope(
            account_id="default",
            currency="",
            instrument_id="BTC-USDT-SWAP",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
    with pytest.raises(ValueError):
        FundingScope(
            account_id="default",
            currency="USDT",
            instrument_id="",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
    with pytest.raises(ValueError):
        FundingScope(
            account_id="default",
            currency="USDT",
            instrument_id="BTC-USDT-SWAP",
            window_start=WINDOW_END,
            window_end=WINDOW_START,
        )


async def test_btc_funding_is_not_attributed_to_sol(ledger):
    await _settle(ledger, instrument_id="BTC-USDT-SWAP")

    btc = await ledger.funding_scope_provenance(
        FundingScope(
            account_id="default",
            currency="USDT",
            instrument_id="BTC-USDT-SWAP",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        ),
        coverage_status="KNOWN_VALUE",
    )
    sol = await ledger.funding_scope_provenance(
        FundingScope(
            account_id="default",
            currency="USDT",
            instrument_id="SOL-USDT-SWAP",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        ),
        coverage_status="KNOWN_ZERO",
    )
    assert btc.complete is True
    assert btc.settled_amount == Decimal("0.001")
    assert sol.complete is True
    assert sol.settled_amount == Decimal("0")


async def test_account_funding_is_isolated(ledger):
    await _settle(ledger, account_id="account-a", quantity="-1")
    await _settle(ledger, account_id="account-b", quantity="-2")

    account_a = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="account-a",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
        coverage_status_by_instrument={"BTC-USDT-SWAP": "KNOWN_VALUE"},
    )
    account_b = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="account-b",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
        coverage_status_by_instrument={"BTC-USDT-SWAP": "KNOWN_VALUE"},
    )
    assert account_a.complete is True
    assert account_a.funding_amount == Decimal("0.001")
    assert account_b.complete is True
    assert account_b.funding_amount == Decimal("0.002")


async def test_currency_funding_is_isolated(ledger):
    await _settle(ledger, currency="USDC", hour=5)
    await _settle(ledger, currency="USDT", quantity="-2", hour=4)

    usdt = await ledger.funding_scope_provenance(
        FundingScope(
            account_id="default",
            currency="USDT",
            instrument_id="BTC-USDT-SWAP",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        ),
        coverage_status="KNOWN_VALUE",
    )
    usdc = await ledger.funding_scope_provenance(
        FundingScope(
            account_id="default",
            currency="USDC",
            instrument_id="BTC-USDT-SWAP",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        ),
        coverage_status="KNOWN_VALUE",
    )
    assert usdt.settled_amount == Decimal("0.002")
    assert usdc.settled_amount == Decimal("0.001")


async def test_null_and_unknown_ownership_is_accounting_incomplete(ledger):
    await _settle(ledger, instrument_id="BTC-USDT-SWAP")
    # Legacy/unverified writer: account claim must not be trusted.
    await ledger.record(
        LedgerEntryType.FUNDING_RECEIPT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
            LedgerPosting("FUNDING_RECEIPT", LedgerDirection.CREDIT, Decimal("5")),
        ],
        account_id="default",
        ownership_status="UNKNOWN",
        instrument_id="BTC-USDT-SWAP",
        transaction_id="txn_unverified",
        created_at=datetime(2026, 9, 10, 4, tzinfo=UTC),
    )
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
        coverage_status_by_instrument={"BTC-USDT-SWAP": "KNOWN_VALUE"},
    )
    assert provenance.complete is False
    assert provenance.funding_status == FundingStatus.ACCOUNTING_INCOMPLETE.value
    assert provenance.funding_amount is None
    assert "UNATTRIBUTED_LEDGER_OWNERSHIP" in provenance.unknown_reasons
    # The known subtotal is still exposed for audit, never as factual PnL.
    assert provenance.known_funding_subtotal == Decimal("0.001")


async def test_null_account_row_flags_incomplete(database, ledger):
    async with database.session_factory() as session:
        session.add(
            LedgerTransactionORM(
                transaction_id="txn_null_account",
                account_id=None,
                instrument_id="BTC-USDT-SWAP",
                ownership_status="UNKNOWN",
                entry_type="FUNDING_RECEIPT",
                created_at=datetime(2026, 9, 10, 4, tzinfo=UTC),
                metadata_json={},
            )
        )
        session.add(
            LedgerEntryORM(
                entry_id="led_null_account",
                transaction_id="txn_null_account",
                seq=1,
                entry_type="FUNDING_RECEIPT",
                account="FUNDING_RECEIPT",
                direction=LedgerDirection.CREDIT.value,
                amount=Decimal("7"),
                currency="USDT",
                created_at=datetime(2026, 9, 10, 4, tzinfo=UTC),
                metadata_json={},
            )
        )
        await session.commit()
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=WINDOW_END,
    )
    assert provenance.complete is False
    assert provenance.funding_status == FundingStatus.ACCOUNTING_INCOMPLETE.value
    assert "UNATTRIBUTED_LEDGER_OWNERSHIP" in provenance.unknown_reasons


async def test_wrong_instrument_posting_cannot_be_dropped(ledger):
    await _settle(ledger, instrument_id="SOL-USDT-SWAP", quantity="-3")
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
        coverage_status_by_instrument={"BTC-USDT-SWAP": "KNOWN_ZERO"},
    )
    assert provenance.complete is False
    assert provenance.funding_status == FundingStatus.ACCOUNTING_INCOMPLETE.value
    assert "FUNDING_COVERAGE_UNKNOWN:SOL-USDT-SWAP" in provenance.unknown_reasons
    assert provenance.required_instruments == ("BTC-USDT-SWAP", "SOL-USDT-SWAP")

    proven = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
        coverage_status_by_instrument={
            "BTC-USDT-SWAP": "KNOWN_ZERO",
            "SOL-USDT-SWAP": "KNOWN_VALUE",
        },
    )
    assert proven.complete is True
    assert proven.funding_amount == Decimal("0.003")
    assert proven.required_instruments == ("BTC-USDT-SWAP", "SOL-USDT-SWAP")


async def test_known_value_coverage_without_posting_is_incomplete(ledger):
    scope = FundingScope(
        account_id="default",
        currency="USDT",
        instrument_id="BTC-USDT-SWAP",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    provenance = await ledger.funding_scope_provenance(scope, coverage_status="KNOWN_VALUE")
    assert provenance.complete is False
    assert provenance.settled_amount is None
    assert "FUNDING_EVENTS_NOT_SETTLED:BTC-USDT-SWAP" in provenance.unknown_reasons


async def test_known_zero_coverage_with_posting_is_contradiction(ledger):
    await _settle(ledger, instrument_id="BTC-USDT-SWAP")
    scope = FundingScope(
        account_id="default",
        currency="USDT",
        instrument_id="BTC-USDT-SWAP",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    provenance = await ledger.funding_scope_provenance(scope, coverage_status="KNOWN_ZERO")
    assert provenance.complete is False
    assert "FUNDING_COVERAGE_CONTRADICTION:BTC-USDT-SWAP" in provenance.unknown_reasons


async def test_unknown_coverage_is_incomplete_not_zero(ledger):
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
    )
    assert provenance.complete is False
    assert provenance.funding_amount is None
    assert provenance.funding_status == FundingStatus.ACCOUNTING_INCOMPLETE.value
    assert "FUNDING_COVERAGE_UNKNOWN:BTC-USDT-SWAP" in provenance.unknown_reasons


async def test_flat_account_with_no_activity_is_not_applicable(ledger):
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=WINDOW_END,
    )
    assert provenance.complete is True
    assert provenance.funding_status == FundingStatus.NOT_APPLICABLE.value
    assert provenance.funding_amount == Decimal("0")


def _risk_signal(side=OrderSide.BUY, quantity="1", metadata=None):
    return SignalIntent(
        signal_id="sig_p0",
        strategy_id="p0-test",
        symbol="BTC-USDT-SWAP",
        side=side,
        quantity=quantity,
        limit_price="100",
        metadata=metadata or {},
    )


def test_risk_rejects_new_exposure_when_accounting_incomplete():
    decision = RiskEngine().check(
        _risk_signal(),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        funding_status="ACCOUNTING_INCOMPLETE",
        pnl_provenance={"complete": False, "funding_status": "ACCOUNTING_INCOMPLETE"},
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "ACCOUNTING_INCOMPLETE"


def test_risk_rejects_new_exposure_on_unknown_funding_status():
    decision = RiskEngine().check(
        _risk_signal(),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        funding_status="UNKNOWN",
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "ACCOUNTING_INCOMPLETE"


def test_risk_still_allows_risk_reducing_action_when_accounting_incomplete():
    position = Position(
        symbol="BTC-USDT-SWAP",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        instrument_type="LINEAR_PERP",
    )
    decision = RiskEngine().check(
        _risk_signal(
            side=OrderSide.SELL,
            quantity="1",
            metadata={"reduce_only": True, "direction": "LONG"},
        ),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=None,
        drawdown=None,
        funding_status="ACCOUNTING_INCOMPLETE",
        pnl_provenance={"complete": False, "funding_status": "ACCOUNTING_INCOMPLETE"},
    )
    assert decision.decision in {
        ExecutionDecision.APPROVE,
        ExecutionDecision.SCALE_DOWN,
    }


def test_risk_rejects_unbounded_or_non_reduce_only_opposite_order():
    position = Position(
        symbol="BTC-USDT-SWAP",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        instrument_type="LINEAR_PERP",
    )
    oversized = RiskEngine().check(
        _risk_signal(side=OrderSide.SELL, quantity="2"),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
        funding_status="KNOWN_VALUE",
    )
    assert oversized.decision == ExecutionDecision.REJECT
    assert oversized.reason == "REDUCE_QUANTITY_EXCEEDS_POSITION"

    # Exactly position-sized but NOT reduce_only is not an accounting-exempt
    # reduction, so incomplete accounting must still reject it.
    non_reduce_only = RiskEngine().check(
        _risk_signal(side=OrderSide.SELL, quantity="1"),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=None,
        funding_status="ACCOUNTING_INCOMPLETE",
        pnl_provenance={"complete": False, "funding_status": "ACCOUNTING_INCOMPLETE"},
    )
    assert non_reduce_only.decision == ExecutionDecision.REJECT
    assert non_reduce_only.reason == "ACCOUNTING_INCOMPLETE"


def test_risk_short_side_reduce_boundary_is_symmetric():
    position = Position(
        symbol="BTC-USDT-SWAP",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("-1"),
        avg_entry_price=Decimal("100"),
        instrument_type="LINEAR_PERP",
    )
    oversized = RiskEngine().check(
        _risk_signal(side=OrderSide.BUY, quantity="2"),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("0"),
    )
    assert oversized.decision == ExecutionDecision.REJECT
    assert oversized.reason == "REDUCE_QUANTITY_EXCEEDS_POSITION"
    bounded = RiskEngine().check(
        _risk_signal(
            side=OrderSide.BUY,
            quantity="1",
            metadata={"reduce_only": True, "direction": "SHORT"},
        ),
        account=Account(balances={}, equity=Decimal("10000")),
        positions={"BTC-USDT-SWAP": position},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=None,
        drawdown=None,
        funding_status="ACCOUNTING_INCOMPLETE",
        pnl_provenance={"complete": False, "funding_status": "ACCOUNTING_INCOMPLETE"},
    )
    assert bounded.decision in {ExecutionDecision.APPROVE, ExecutionDecision.SCALE_DOWN}


async def test_window_boundary_is_half_open(ledger):
    # Settlement at the exact window end belongs to the next window.
    settlement = compute_paper_funding(
        settlement_timestamp=WINDOW_END,
        signed_quantity=Decimal("-1"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        instrument_id="BTC-USDT-SWAP",
    )
    await ledger.apply_paper_funding_settlement(settlement)
    scope = FundingScope(
        account_id="default",
        currency="USDT",
        instrument_id="BTC-USDT-SWAP",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    provenance = await ledger.funding_scope_provenance(scope, coverage_status="KNOWN_ZERO")
    assert provenance.complete is True
    assert provenance.posting_count == 0

    next_window = FundingScope(
        account_id="default",
        currency="USDT",
        instrument_id="BTC-USDT-SWAP",
        window_start=WINDOW_END,
        window_end=WINDOW_END + timedelta(hours=8),
    )
    provenance = await ledger.funding_scope_provenance(next_window, coverage_status="KNOWN_VALUE")
    assert provenance.complete is True
    assert provenance.posting_count == 1


async def test_closed_instrument_activity_still_requires_funding_coverage(ledger):
    # No open positions at all: funding coverage must still be required for an
    # instrument that produced realized PnL inside the window.
    await ledger.record(
        LedgerEntryType.TRADE,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
            LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, Decimal("5")),
        ],
        account_id="default",
        instrument_id="SOL-USDT-SWAP",
        transaction_id="closed_sol_pnl",
        created_at=WINDOW_START + timedelta(hours=2),
    )
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=WINDOW_END,
    )
    assert provenance.complete is False
    assert provenance.required_instruments == ("SOL-USDT-SWAP",)
    assert "FUNDING_COVERAGE_UNKNOWN:SOL-USDT-SWAP" in provenance.unknown_reasons
    assert provenance.funding_amount is None


async def test_unverified_ownership_blocks_every_account(ledger):
    await ledger.record(
        LedgerEntryType.FUNDING_RECEIPT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
            LedgerPosting("FUNDING_RECEIPT", LedgerDirection.CREDIT, Decimal("5")),
        ],
        account_id="default",
        ownership_status="UNKNOWN",
        instrument_id="BTC-USDT-SWAP",
        transaction_id="unknown_claim",
        created_at=WINDOW_START + timedelta(hours=1),
    )
    # The retained 'default' label is an unproven claim; account-a cannot
    # silently ignore it and report a factual zero.
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="account-a",
        currency="USDT",
        instrument_ids=[],
        end=WINDOW_END,
    )
    assert provenance.complete is False
    assert provenance.funding_status == FundingStatus.ACCOUNTING_INCOMPLETE.value
    assert "UNATTRIBUTED_LEDGER_OWNERSHIP" in provenance.unknown_reasons


async def test_record_without_account_is_unknown_not_default(ledger, database):
    await ledger.record(
        LedgerEntryType.FUNDING_RECEIPT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
            LedgerPosting("FUNDING_RECEIPT", LedgerDirection.CREDIT, Decimal("5")),
        ],
        instrument_id="BTC-USDT-SWAP",
        transaction_id="omitted_identity",
        created_at=WINDOW_START + timedelta(hours=1),
    )
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.transaction_id == "omitted_identity"
                )
            )
        ).scalar_one()
    assert row.account_id is None
    assert row.ownership_status == "UNKNOWN"
    provenance = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=WINDOW_END,
        coverage_status_by_instrument={"BTC-USDT-SWAP": "KNOWN_VALUE"},
    )
    assert provenance.complete is False
    assert "UNATTRIBUTED_LEDGER_OWNERSHIP" in provenance.unknown_reasons


async def test_closed_instrument_window_end_scopes_funding_coverage(ledger):
    # A closed swap produced realized PnL at 04:00; it only requires proven
    # funding coverage for the factual hold interval, not post-close events.
    await ledger.record(
        LedgerEntryType.TRADE,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
            LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, Decimal("5")),
        ],
        account_id="default",
        instrument_id="SOL-USDT-SWAP",
        transaction_id="closed_sol_window",
        created_at=WINDOW_START + timedelta(hours=4),
    )
    open_start = WINDOW_START + timedelta(hours=2)
    close_end = WINDOW_START + timedelta(hours=4, minutes=30)
    proven_zero = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=WINDOW_END,
        coverage_status_by_instrument={"SOL-USDT-SWAP": "KNOWN_ZERO"},
        instrument_window_starts={"SOL-USDT-SWAP": open_start},
        instrument_window_ends={"SOL-USDT-SWAP": close_end},
    )
    assert proven_zero.complete is True
    assert proven_zero.required_instruments == ("SOL-USDT-SWAP",)

    missing_coverage = await ledger.net_pnl_provenance_since(
        WINDOW_START,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=WINDOW_END,
        instrument_window_starts={"SOL-USDT-SWAP": open_start},
        instrument_window_ends={"SOL-USDT-SWAP": close_end},
    )
    assert missing_coverage.complete is False
    assert "FUNDING_COVERAGE_UNKNOWN:SOL-USDT-SWAP" in missing_coverage.unknown_reasons
