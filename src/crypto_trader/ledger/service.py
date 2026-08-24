"""Append-only double-entry ledger.

PORTED from Kalshi v2 lib/v2/ledger.mjs:
- atomic multi-entry journals
- debits == credits invariant before persistence
- no direct account balance mutation

Ported as semantics in Python/SQLAlchemy; Kalshi-specific paper settlement
legs were replaced by crypto spot trade journals defined in SPAC section 6.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType, OrderSide
from crypto_trader.domain.errors import JournalUnbalanced
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import LedgerEntry, LedgerTransaction
from crypto_trader.domain.money import D
from crypto_trader.persistence.models import LedgerEntryORM, LedgerTransactionORM


@dataclass(frozen=True)
class LedgerPosting:
    account: str
    direction: LedgerDirection
    amount: Decimal
    currency: str = "USDT"


def journal_balanced(postings: list[LedgerPosting]) -> bool:
    debits = sum((p.amount for p in postings if p.direction == LedgerDirection.DEBIT), Decimal("0"))
    credits = sum((p.amount for p in postings if p.direction == LedgerDirection.CREDIT), Decimal("0"))
    return debits == credits


def build_trade_entries(
    *,
    side: OrderSide,
    symbol: str,
    quote_currency: str,
    price: Decimal,
    quantity: Decimal,
    fee: Decimal,
    cost_released: Decimal | None = None,
) -> tuple[list[LedgerPosting], dict]:
    """Build balanced spot-trade journal postings (SPAC section 6)."""
    price = D(price)
    quantity = D(quantity)
    fee = D(fee)
    gross = price * quantity
    postings: list[LedgerPosting] = []
    metadata: dict = {
        "symbol": symbol,
        "quote_currency": quote_currency,
        "side": side.value,
        "quantity": str(quantity),
        "price": str(price),
        "fee": str(fee),
    }
    if side == OrderSide.BUY:
        postings.append(LedgerPosting(f"POSITION_ASSET:{symbol}", LedgerDirection.DEBIT, gross, quote_currency))
        postings.append(LedgerPosting("FEE_EXPENSE", LedgerDirection.DEBIT, fee, quote_currency))
        postings.append(LedgerPosting("CASH", LedgerDirection.CREDIT, gross + fee, quote_currency))
        metadata["gross_cost"] = str(gross)
    else:
        cost_released = D(cost_released if cost_released is not None else Decimal("0"))
        realized = gross - cost_released
        postings.append(LedgerPosting("CASH", LedgerDirection.DEBIT, gross, quote_currency))
        postings.append(LedgerPosting(f"POSITION_ASSET:{symbol}", LedgerDirection.CREDIT, cost_released, quote_currency))
        if realized > 0:
            postings.append(LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, realized, quote_currency))
        elif realized < 0:
            postings.append(LedgerPosting("REALIZED_PNL", LedgerDirection.DEBIT, -realized, quote_currency))
        postings.append(LedgerPosting("FEE_EXPENSE", LedgerDirection.DEBIT, fee, quote_currency))
        postings.append(LedgerPosting("CASH", LedgerDirection.CREDIT, fee, quote_currency))
        metadata["gross_proceeds"] = str(gross)
        metadata["cost_released"] = str(cost_released)
        metadata["realized_pnl"] = str(realized)
    if not journal_balanced(postings):
        raise JournalUnbalanced("generated trade journal is not balanced")
    return postings, metadata


class LedgerService:
    """Atomic ledger writer and reader."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def record(
        self,
        entry_type: LedgerEntryType,
        postings: list[LedgerPosting],
        *,
        transaction_id: str | None = None,
        order_id: str | None = None,
        fill_id: str | None = None,
        event_id: str | None = None,
        metadata: dict | None = None,
        created_at: datetime | None = None,
    ) -> LedgerTransaction:
        if not postings:
            raise JournalUnbalanced("ledger transaction requires at least one posting")
        if not journal_balanced(postings):
            debits = sum((p.amount for p in postings if p.direction == LedgerDirection.DEBIT), Decimal("0"))
            credits = sum((p.amount for p in postings if p.direction == LedgerDirection.CREDIT), Decimal("0"))
            raise JournalUnbalanced(f"journal unbalanced: debit={debits} credit={credits}")
        transaction_id = transaction_id or new_id("txn")
        created_at = created_at or datetime.now(timezone.utc)
        async with self.session_factory() as session:
            txn = LedgerTransactionORM(
                transaction_id=transaction_id,
                entry_type=entry_type.value,
                created_at=created_at,
                order_id=order_id,
                fill_id=fill_id,
                event_id=event_id,
                metadata_json=metadata or {},
            )
            session.add(txn)
            for seq, posting in enumerate(postings, start=1):
                session.add(
                    LedgerEntryORM(
                        entry_id=new_id("led"),
                        transaction_id=transaction_id,
                        seq=seq,
                        entry_type=entry_type.value,
                        account=posting.account,
                        direction=posting.direction.value,
                        amount=posting.amount,
                        currency=posting.currency,
                        created_at=created_at,
                        order_id=order_id,
                        fill_id=fill_id,
                        event_id=event_id,
                        metadata_json={},
                    )
                )
            await session.commit()
        return LedgerTransaction(
            transaction_id=transaction_id,
            entry_type=entry_type,
            created_at=created_at,
            metadata=metadata or {},
            entries=[
                LedgerEntry(
                    entry_id="pending",
                    transaction_id=transaction_id,
                    seq=i,
                    entry_type=entry_type,
                    account=p.account,
                    direction=p.direction,
                    amount=p.amount,
                    currency=p.currency,
                    created_at=created_at,
                    order_id=order_id,
                    fill_id=fill_id,
                    event_id=event_id,
                )
                for i, p in enumerate(postings, start=1)
            ],
        )

    async def list_transactions(self, session: AsyncSession) -> list[LedgerTransactionORM]:
        result = await session.execute(
            select(LedgerTransactionORM).order_by(
                LedgerTransactionORM.created_at, LedgerTransactionORM.transaction_id
            )
        )
        return list(result.scalars().all())


async def _txn_to_domain(txn: LedgerTransactionORM) -> LedgerTransaction:
    entries = [
        LedgerEntry(
            entry_id=e.entry_id,
            transaction_id=e.transaction_id,
            seq=e.seq,
            entry_type=LedgerEntryType(e.entry_type),
            account=e.account,
            direction=LedgerDirection(e.direction),
            amount=e.amount,
            currency=e.currency,
            created_at=e.created_at,
            order_id=e.order_id,
            fill_id=e.fill_id,
            event_id=e.event_id,
            metadata=e.metadata_json or {},
        )
        for e in sorted(txn.entries, key=lambda x: x.seq)
    ]
    return LedgerTransaction(
        transaction_id=txn.transaction_id,
        entry_type=LedgerEntryType(txn.entry_type),
        created_at=txn.created_at,
        metadata=txn.metadata_json or {},
        entries=entries,
    )
