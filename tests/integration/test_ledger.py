from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType, OrderSide
from crypto_trader.domain.errors import JournalUnbalanced
from crypto_trader.ledger.projections import ProjectionBuilder, replay_projections
from crypto_trader.ledger.service import LedgerPosting, LedgerService, build_trade_entries
from crypto_trader.persistence.models import LedgerEntryORM


@pytest.fixture
def ledger(database):
    return LedgerService(database.session_factory)


async def test_ledger_rejects_unbalanced_journal(ledger):
    with pytest.raises(JournalUnbalanced):
        await ledger.record(
            LedgerEntryType.DEPOSIT,
            [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100")),
             LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("99"))],
        )


async def test_ledger_atomic_and_unique_transaction_id(ledger, database):
    txn_id = "txn_atomic_1"
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("1000")),
         LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("1000"))],
        transaction_id=txn_id,
    )
    with pytest.raises(IntegrityError):
        await ledger.record(
            LedgerEntryType.DEPOSIT,
            [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
             LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("5"))],
            transaction_id=txn_id,
        )


async def test_ledger_decimal_roundtrip_exact(ledger, database):
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("123456789.12345678")),
         LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("123456789.12345678"))],
        transaction_id="txn_exact_1",
    )
    async with database.session_factory() as s:
        row = (await s.execute(select(LedgerEntryORM))).scalars().first()
        assert row.amount == Decimal("123456789.12345678")


async def test_build_trade_entries_are_balanced():
    buy, buy_meta = build_trade_entries(
        side=OrderSide.BUY, symbol="BTCUSDT", quote_currency="USDT",
        price=Decimal("100.5"), quantity=Decimal("0.25"), fee=Decimal("1.0"),
    )
    assert sum((p.amount for p in buy if p.direction == LedgerDirection.DEBIT), Decimal("0")) == \
        sum((p.amount for p in buy if p.direction == LedgerDirection.CREDIT), Decimal("0"))
    assert buy_meta["side"] == "BUY"

    sell, _ = build_trade_entries(
        side=OrderSide.SELL, symbol="BTCUSDT", quote_currency="USDT",
        price=Decimal("110"), quantity=Decimal("0.25"), fee=Decimal("1.0"),
        cost_released=Decimal("25.125"),
    )
    debits = sum((p.amount for p in sell if p.direction == LedgerDirection.DEBIT), Decimal("0"))
    credits = sum((p.amount for p in sell if p.direction == LedgerDirection.CREDIT), Decimal("0"))
    assert debits == credits


async def test_replay_builds_correct_projections(ledger, database):
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("10000")),
         LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("10000"))],
        transaction_id="txn_deposit",
        metadata={"amount": "10000"},
    )
    buy_postings, buy_meta = build_trade_entries(
        side=OrderSide.BUY, symbol="BTCUSDT", quote_currency="USDT",
        price=Decimal("100"), quantity=Decimal("1"), fee=Decimal("0.1"),
    )
    buy_meta["base_asset"] = "BTC"
    await ledger.record(LedgerEntryType.TRADE, buy_postings, transaction_id="txn_buy", metadata=buy_meta)
    sell_postings, sell_meta = build_trade_entries(
        side=OrderSide.SELL, symbol="BTCUSDT", quote_currency="USDT",
        price=Decimal("120"), quantity=Decimal("0.5"), fee=Decimal("0.06"),
        cost_released=Decimal("50"),
    )
    sell_meta["base_asset"] = "BTC"
    await ledger.record(LedgerEntryType.TRADE, sell_postings, transaction_id="txn_sell", metadata=sell_meta)

    async with database.session_factory() as s:
        snap = await replay_projections(s, initial_balances={"USDT": Decimal("0")})
        assert snap.balance("USDT") == Decimal("9959.84")
        pos = snap.positions["BTCUSDT"]
        assert pos.quantity == Decimal("0.5")
        assert pos.avg_entry_price == Decimal("100")
        assert snap.realized_pnl == Decimal("10")
        assert snap.total_fees == Decimal("0.16")


async def test_replay_is_deterministic_and_rebuild_matches(ledger, database):
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("500")),
         LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("500"))],
        transaction_id="txn_r_deposit",
        metadata={"amount": "500"},
    )
    for i in range(5):
        postings, meta = build_trade_entries(
            side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
            symbol="ETHUSDT", quote_currency="USDT",
            price=Decimal("10") + Decimal(i),
            quantity=Decimal("1.5"),
            fee=Decimal("0.01"),
            cost_released=Decimal("15") if i % 2 == 1 else None,
        )
        meta["base_asset"] = "ETH"
        await ledger.record(LedgerEntryType.TRADE, postings, transaction_id=f"txn_r_{i}", metadata=meta)
    async with database.session_factory() as s:
        before = await replay_projections(s, initial_balances={"USDT": Decimal("0")})
    from crypto_trader.ledger.projections import rebuild_projections
    async with database.session_factory() as s:
        rebuilt = await rebuild_projections(s, initial_balances={"USDT": Decimal("0")})
    async with database.session_factory() as s:
        after = await replay_projections(s, initial_balances={"USDT": Decimal("0")})
    assert before.as_plain() == after.as_plain()
    assert rebuilt.as_plain() == after.as_plain()
