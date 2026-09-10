from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType, OrderSide
from crypto_trader.domain.errors import JournalUnbalanced
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.ledger.projections import replay_projections
from crypto_trader.ledger.service import LedgerPosting, LedgerService, build_trade_entries
from crypto_trader.persistence.models import LedgerEntryORM, TradeEpisodeORM
from crypto_trader.portfolio.service import PortfolioService


@pytest.fixture
def ledger(database):
    return LedgerService(database.session_factory)


async def test_ledger_rejects_unbalanced_journal(ledger):
    with pytest.raises(JournalUnbalanced):
        await ledger.record(
            LedgerEntryType.DEPOSIT,
            [
                LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100")),
                LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("99")),
            ],
        )


async def test_ledger_atomic_and_unique_transaction_id(ledger, database):
    txn_id = "txn_atomic_1"
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("1000")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("1000")),
        ],
        transaction_id=txn_id,
    )
    with pytest.raises(IntegrityError):
        await ledger.record(
            LedgerEntryType.DEPOSIT,
            [
                LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("5")),
                LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("5")),
            ],
            transaction_id=txn_id,
        )


async def test_ledger_decimal_roundtrip_exact(ledger, database):
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("123456789.12345678")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("123456789.12345678")),
        ],
        transaction_id="txn_exact_1",
    )
    async with database.session_factory() as s:
        row = (await s.execute(select(LedgerEntryORM))).scalars().first()
        assert row.amount == Decimal("123456789.12345678")


async def test_build_trade_entries_are_balanced():
    buy, buy_meta = build_trade_entries(
        side=OrderSide.BUY,
        symbol="BTCUSDT",
        quote_currency="USDT",
        price=Decimal("100.5"),
        quantity=Decimal("0.25"),
        fee=Decimal("1.0"),
    )
    assert sum(
        (p.amount for p in buy if p.direction == LedgerDirection.DEBIT), Decimal("0")
    ) == sum((p.amount for p in buy if p.direction == LedgerDirection.CREDIT), Decimal("0"))
    assert buy_meta["side"] == "BUY"

    sell, _ = build_trade_entries(
        side=OrderSide.SELL,
        symbol="BTCUSDT",
        quote_currency="USDT",
        price=Decimal("110"),
        quantity=Decimal("0.25"),
        fee=Decimal("1.0"),
        cost_released=Decimal("25.125"),
    )
    debits = sum((p.amount for p in sell if p.direction == LedgerDirection.DEBIT), Decimal("0"))
    credits = sum((p.amount for p in sell if p.direction == LedgerDirection.CREDIT), Decimal("0"))
    assert debits == credits


async def test_replay_builds_correct_projections(ledger, database):
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("10000")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("10000")),
        ],
        transaction_id="txn_deposit",
        metadata={"amount": "10000"},
    )
    buy_postings, buy_meta = build_trade_entries(
        side=OrderSide.BUY,
        symbol="BTCUSDT",
        quote_currency="USDT",
        price=Decimal("100"),
        quantity=Decimal("1"),
        fee=Decimal("0.1"),
    )
    buy_meta["base_asset"] = "BTC"
    await ledger.record(
        LedgerEntryType.TRADE, buy_postings, transaction_id="txn_buy", metadata=buy_meta
    )
    sell_postings, sell_meta = build_trade_entries(
        side=OrderSide.SELL,
        symbol="BTCUSDT",
        quote_currency="USDT",
        price=Decimal("120"),
        quantity=Decimal("0.5"),
        fee=Decimal("0.06"),
        cost_released=Decimal("50"),
    )
    sell_meta["base_asset"] = "BTC"
    await ledger.record(
        LedgerEntryType.TRADE, sell_postings, transaction_id="txn_sell", metadata=sell_meta
    )

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
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("500")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("500")),
        ],
        transaction_id="txn_r_deposit",
        metadata={"amount": "500"},
    )
    for i in range(5):
        postings, meta = build_trade_entries(
            side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
            symbol="ETHUSDT",
            quote_currency="USDT",
            price=Decimal("10") + Decimal(i),
            quantity=Decimal("1.5"),
            fee=Decimal("0.01"),
            cost_released=Decimal("15") if i % 2 == 1 else None,
        )
        meta["base_asset"] = "ETH"
        await ledger.record(
            LedgerEntryType.TRADE, postings, transaction_id=f"txn_r_{i}", metadata=meta
        )
    async with database.session_factory() as s:
        before = await replay_projections(s, initial_balances={"USDT": Decimal("0")})
    from crypto_trader.ledger.projections import rebuild_projections

    async with database.session_factory() as s:
        rebuilt = await rebuild_projections(s, initial_balances={"USDT": Decimal("0")})
    async with database.session_factory() as s:
        after = await replay_projections(s, initial_balances={"USDT": Decimal("0")})
    assert before.as_plain() == after.as_plain()
    assert rebuilt.as_plain() == after.as_plain()



async def test_ledger_realized_pnl_since_utc_boundary(ledger, database):
    from datetime import UTC, datetime, timedelta

    await ledger.record(
        LedgerEntryType.TRADE,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("10")),
            LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, Decimal("10")),
        ],
        transaction_id="pnl_profit",
    )
    await ledger.record(
        LedgerEntryType.TRADE,
        [
            LedgerPosting("REALIZED_PNL", LedgerDirection.DEBIT, Decimal("4")),
            LedgerPosting("CASH", LedgerDirection.CREDIT, Decimal("4")),
        ],
        transaction_id="pnl_loss",
    )
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    assert await ledger.realized_pnl_since(start) == Decimal("6")
    # Future start returns zero
    assert await ledger.realized_pnl_since(start + timedelta(days=1)) == Decimal("0")


async def test_equity_peak_is_durable_across_service_restart(database):
    first = PortfolioService(database.session_factory)
    dd0, peak0, _, _ = await first.record_equity_drawdown(Decimal("100000"))
    assert dd0 == Decimal("0")
    assert peak0 == Decimal("100000")
    dd1, peak1, _, _ = await first.record_equity_drawdown(Decimal("95000"))
    assert dd1 == Decimal("-5000")
    assert peak1 == Decimal("100000")

    second = PortfolioService(database.session_factory)
    dd2, peak2, _, _ = await second.record_equity_drawdown(Decimal("94000"))
    assert dd2 == Decimal("-6000")
    assert peak2 == Decimal("100000")


async def test_earliest_factual_closed_episode_date_ignores_non_factual(database):
    from datetime import UTC, datetime

    async with database.session_factory() as session:
        session.add(
            TradeEpisodeORM(
                episode_id="ep_factual_early",
                trade_plan_id="plan_early",
                symbol="BTCUSDT",
                direction="LONG",
                entry_decision_id="d1",
                entry_price=Decimal("100"),
                exit_price=Decimal("101"),
                opened_quantity=Decimal("1"),
                closed_quantity=Decimal("1"),
                leverage=Decimal("1"),
                gross_pnl=Decimal("1"),
                net_pnl=Decimal("1"),
                holding_time_seconds=1.0,
                entry_market_regime="TREND",
                terminal_reason="EXIT",
                factual=True,
                opened_at=datetime(2026, 9, 7, tzinfo=UTC),
                closed_at=datetime(2026, 9, 8, tzinfo=UTC),
            )
        )
        session.add(
            TradeEpisodeORM(
                episode_id="ep_non_factual",
                trade_plan_id="plan_non_factual",
                symbol="BTCUSDT",
                direction="LONG",
                entry_decision_id="d2",
                entry_price=Decimal("100"),
                exit_price=Decimal("101"),
                opened_quantity=Decimal("1"),
                closed_quantity=Decimal("1"),
                leverage=Decimal("1"),
                gross_pnl=Decimal("1"),
                net_pnl=Decimal("1"),
                holding_time_seconds=1.0,
                entry_market_regime="TREND",
                terminal_reason="EXIT",
                factual=False,
                opened_at=datetime(2026, 9, 1, tzinfo=UTC),
                closed_at=datetime(2026, 9, 2, tzinfo=UTC),
            )
        )
        await session.commit()

    store = TradeEpisodeStore(database.session_factory)
    assert await store.earliest_factual_closed_date() == "2026-09-08"


async def test_funding_status_unknown_without_source_coverage(ledger):
    from datetime import UTC, datetime

    from crypto_trader.ledger.service import FundingStatus

    start = datetime(2026, 9, 10, tzinfo=UTC)
    assert await ledger.funding_status_since(start) == FundingStatus.UNKNOWN


async def test_funding_status_known_value_with_posting(ledger):
    from datetime import UTC, datetime

    from crypto_trader.ledger.service import FundingStatus

    start = datetime(2026, 9, 10, tzinfo=UTC)
    await ledger.record(
        LedgerEntryType.FUNDING_RECEIPT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("2")),
            LedgerPosting("FUNDING_RECEIPT", LedgerDirection.CREDIT, Decimal("2")),
        ],
        transaction_id="funding_receipt_1",
    )
    assert await ledger.funding_status_since(start) == FundingStatus.KNOWN_VALUE


async def test_daily_review_pagination_reads_more_than_1000_episodes(database):
    from datetime import UTC, datetime

    from crypto_trader.governance.trade_episode import TradeEpisodeStore

    async with database.session_factory() as session:
        for i in range(1001):
            session.add(
                TradeEpisodeORM(
                    episode_id=f"ep_page_{i:04d}",
                    trade_plan_id=f"plan_page_{i:04d}",
                    symbol="BTCUSDT",
                    direction="LONG",
                    entry_decision_id="d",
                    entry_price=Decimal("100"),
                    exit_price=Decimal("101"),
                    opened_quantity=Decimal("1"),
                    closed_quantity=Decimal("1"),
                    leverage=Decimal("1"),
                    gross_pnl=Decimal("1"),
                    net_pnl=Decimal("1"),
                    holding_time_seconds=1.0,
                    entry_market_regime="TREND",
                    terminal_reason="EXIT",
                    factual=True,
                    opened_at=datetime(2026, 9, 8, tzinfo=UTC),
                    closed_at=datetime(2026, 9, 8, 12, tzinfo=UTC),
                )
            )
        await session.commit()
    store = TradeEpisodeStore(database.session_factory)
    episodes = await store.load_all_closed_on("2026-09-08")
    assert len(episodes) == 1001


async def test_equity_drawdown_isolated_by_account_and_currency(database):
    service = PortfolioService(database.session_factory)
    await service.record_equity_drawdown(Decimal("100"), account_id="A", currency="USDT")
    await service.record_equity_drawdown(Decimal("50"), account_id="B", currency="USDT")
    dd_a, peak_a, _, _ = await service.record_equity_drawdown(
        Decimal("90"), account_id="A", currency="USDT"
    )
    dd_b, peak_b, _, _ = await service.record_equity_drawdown(
        Decimal("50"), account_id="B", currency="USDT"
    )
    assert dd_a == Decimal("-10") and peak_a == Decimal("100")
    assert dd_b == Decimal("0") and peak_b == Decimal("50")


def test_equity_status_classification():
    from crypto_trader.portfolio.service import PortfolioService

    assert PortfolioService.classify_equity_status(Decimal("1")) == "HEALTHY"
    assert PortfolioService.classify_equity_status(Decimal("0")) == "ZERO_EQUITY"
    assert PortfolioService.classify_equity_status(Decimal("-1")) == "INSOLVENT"
