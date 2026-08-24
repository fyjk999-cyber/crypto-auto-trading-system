from decimal import Decimal

import pytest

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType, OrderSide
from crypto_trader.domain.models import Balance as BalanceModel, Position
from crypto_trader.ledger.service import LedgerPosting, LedgerService, build_trade_entries
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService


class StubAdapter:
    def __init__(self):
        self.balances = [BalanceModel(currency="USDT", total=Decimal("0"), available=Decimal("0"), frozen=Decimal("0"))]
        self.positions: list[Position] = []

    async def get_balances(self):
        return self.balances

    async def get_positions(self):
        return self.positions


async def seed_deposit(ledger, amount="1000", txn="txn_seed_deposit"):
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal(amount)),
         LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal(amount))],
        transaction_id=txn,
        metadata={"amount": amount},
    )


async def test_portfolio_projection_after_ledger_trades(database):
    ledger = LedgerService(database.session_factory)
    portfolio = PortfolioService(database.session_factory)
    await seed_deposit(ledger)
    postings, meta = build_trade_entries(
        side=OrderSide.BUY, symbol="BTCUSDT", quote_currency="USDT",
        price=Decimal("100"), quantity=Decimal("0.5"), fee=Decimal("0.1"),
    )
    meta["base_asset"] = "BTC"
    await ledger.record(LedgerEntryType.TRADE, postings, transaction_id="txn_buy_p", metadata=meta)
    await portfolio.refresh(initial_balances={"USDT": Decimal("0")})

    account = await portfolio.get_account()
    assert account.balances["USDT"].total == Decimal("949.9")
    positions = await portfolio.get_positions()
    assert positions["BTCUSDT"].quantity == Decimal("0.5")
    assert positions["BTCUSDT"].avg_entry_price == Decimal("100")


async def test_reconciliation_detects_balance_mismatch(database):
    ledger = LedgerService(database.session_factory)
    await seed_deposit(ledger)
    adapter = StubAdapter()
    adapter.balances[0] = BalanceModel(currency="USDT", total=Decimal("999"), available=Decimal("999"), frozen=Decimal("0"))
    service = ReconciliationService(database.session_factory)
    report = await service.reconcile(adapter)
    assert report.ok is False
    assert report.halt is True
    assert any("BALANCE_MISMATCH USDT" in a for a in report.alerts)


async def test_reconciliation_passes_when_equal(database):
    ledger = LedgerService(database.session_factory)
    await seed_deposit(ledger, amount="1000")
    adapter = StubAdapter()
    adapter.balances[0] = BalanceModel(currency="USDT", total=Decimal("1000"), available=Decimal("1000"), frozen=Decimal("0"))
    service = ReconciliationService(database.session_factory)
    report = await service.reconcile(adapter)
    assert report.ok is True
    assert report.halt is False


async def test_reconciliation_detects_position_mismatch(database):
    ledger = LedgerService(database.session_factory)
    await seed_deposit(ledger)
    postings, meta = build_trade_entries(
        side=OrderSide.BUY, symbol="BTCUSDT", quote_currency="USDT",
        price=Decimal("100"), quantity=Decimal("1"), fee=Decimal("0"),
    )
    meta["base_asset"] = "BTC"
    await ledger.record(LedgerEntryType.TRADE, postings, transaction_id="txn_buy_pos", metadata=meta)
    adapter = StubAdapter()
    adapter.balances[0] = BalanceModel(currency="USDT", total=Decimal("900"), available=Decimal("900"), frozen=Decimal("0"))
    service = ReconciliationService(database.session_factory)
    report = await service.reconcile(adapter)
    assert any("POSITION_MISMATCH BTCUSDT" in a for a in report.alerts)
    assert report.halt is True
