from decimal import Decimal

from crypto_trader.perpetual.domain import PerpetualContract, PositionSide
from crypto_trader.perpetual.engine import PerpetualPaperEngine
from crypto_trader.perpetual.ledger import rebuild_futures_projection


def make_contract():
    return PerpetualContract(
        symbol="BTCUSDT_PERP",
        base="BTC",
        quote="USDT",
        settlement_asset="USDT",
        max_leverage=Decimal("6"),
        taker_fee_rate=Decimal("0.0005"),
    )


async def test_perpetual_long_open_mark_funding_close(database):
    contract = make_contract()
    engine = PerpetualPaperEngine(database.session_factory, contract)
    pos = await engine.open_position(PositionSide.LONG, Decimal("1"), Decimal("100"), Decimal("5"))
    assert pos.side == PositionSide.LONG
    assert pos.quantity == Decimal("1")
    assert pos.initial_margin == Decimal("20")
    marked = await engine.mark_to_market(Decimal("110"))
    assert marked.unrealized_pnl == Decimal("10")
    funding = await engine.apply_funding(Decimal("0.0001"), Decimal("110"))
    assert funding < 0  # long pays
    closed = await engine.close_position(PositionSide.LONG, Decimal("1"), Decimal("110"))
    assert closed is None or closed.is_flat
    async with database.session_factory() as session:
        snap = await rebuild_futures_projection(session)
    assert snap.realized_pnl == Decimal("10")
    assert snap.funding_paid > 0
    assert snap.fees_paid > 0


async def test_perpetual_short_open_mark_funding_close(database):
    contract = make_contract()
    engine = PerpetualPaperEngine(database.session_factory, contract)
    pos = await engine.open_position(PositionSide.SHORT, Decimal("1"), Decimal("100"), Decimal("5"))
    assert pos.side == PositionSide.SHORT
    assert pos.quantity == Decimal("-1")
    marked = await engine.mark_to_market(Decimal("90"))
    assert marked.unrealized_pnl == Decimal("10")
    funding = await engine.apply_funding(Decimal("0.0001"), Decimal("90"))
    assert funding > 0  # short receives
    closed = await engine.close_position(PositionSide.SHORT, Decimal("1"), Decimal("90"))
    assert closed is None or closed.is_flat
    async with database.session_factory() as session:
        snap = await rebuild_futures_projection(session)
    assert snap.realized_pnl == Decimal("10")
    assert snap.funding_received > 0


async def test_perpetual_liquidation_long_and_short(database):
    contract = make_contract()
    engine = PerpetualPaperEngine(database.session_factory, contract)
    await engine.open_position(PositionSide.LONG, Decimal("1"), Decimal("100"), Decimal("5"))
    liquidated = await engine.liquidate(Decimal("80"))
    assert liquidated is True
    async with database.session_factory() as session:
        snap = await rebuild_futures_projection(session)
    assert snap.positions.get(contract.symbol) is None

    engine2 = PerpetualPaperEngine(database.session_factory, contract)
    await engine2.open_position(PositionSide.SHORT, Decimal("1"), Decimal("100"), Decimal("5"))
    liquidated2 = await engine2.liquidate(Decimal("120"))
    assert liquidated2 is True


async def test_futures_projection_rebuild_before_after(database):
    contract = make_contract()
    engine = PerpetualPaperEngine(database.session_factory, contract)
    await engine.open_position(PositionSide.LONG, Decimal("2"), Decimal("100"), Decimal("5"))
    await engine.mark_to_market(Decimal("102"))
    async with database.session_factory() as session:
        before = await rebuild_futures_projection(session)
    async with database.session_factory() as session:
        after = await rebuild_futures_projection(session)
    assert before.positions[contract.symbol].quantity == after.positions[contract.symbol].quantity
    assert before.realized_pnl == after.realized_pnl
    assert before.fees_paid == after.fees_paid


async def test_futures_ledger_journal_balanced(database):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from crypto_trader.domain.enums import LedgerDirection
    from crypto_trader.ledger.service import LedgerService, journal_balanced
    from crypto_trader.perpetual.ledger import FuturesLedger
    from crypto_trader.persistence.models import LedgerTransactionORM

    contract = make_contract()
    fl = FuturesLedger(LedgerService(database.session_factory))
    await fl.record_open(
        contract,
        PositionSide.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("5"),
        Decimal("20"),
        Decimal("0.05"),
    )
    await fl.record_close(
        contract,
        PositionSide.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("105"),
        Decimal("5"),
        Decimal("0.0525"),
        Decimal("20"),
    )
    async with database.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(LedgerTransactionORM).options(selectinload(LedgerTransactionORM.entries))
                )
            )
            .scalars()
            .all()
        )
        for txn in rows:
            postings = []
            for e in txn.entries:
                from crypto_trader.ledger.service import LedgerPosting

                postings.append(
                    LedgerPosting(e.account, LedgerDirection(e.direction), e.amount, e.currency)
                )
            assert journal_balanced(postings)
