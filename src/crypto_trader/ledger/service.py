"""Append-only double-entry ledger.

PORTED from the reference v2 ledger module:
- atomic multi-entry journals
- debits == credits invariant before persistence
- no direct account balance mutation

Ported as semantics in Python/SQLAlchemy; reference-specific paper settlement
legs were replaced by crypto spot trade journals defined in SPAC section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    credits = sum(
        (p.amount for p in postings if p.direction == LedgerDirection.CREDIT), Decimal("0")
    )
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
        postings.append(
            LedgerPosting(f"POSITION_ASSET:{symbol}", LedgerDirection.DEBIT, gross, quote_currency)
        )
        postings.append(LedgerPosting("FEE_EXPENSE", LedgerDirection.DEBIT, fee, quote_currency))
        postings.append(LedgerPosting("CASH", LedgerDirection.CREDIT, gross + fee, quote_currency))
        metadata["gross_cost"] = str(gross)
    else:
        cost_released = D(cost_released if cost_released is not None else Decimal("0"))
        realized = gross - cost_released
        postings.append(LedgerPosting("CASH", LedgerDirection.DEBIT, gross, quote_currency))
        postings.append(
            LedgerPosting(
                f"POSITION_ASSET:{symbol}", LedgerDirection.CREDIT, cost_released, quote_currency
            )
        )
        if realized > 0:
            postings.append(
                LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, realized, quote_currency)
            )
        elif realized < 0:
            postings.append(
                LedgerPosting("REALIZED_PNL", LedgerDirection.DEBIT, -realized, quote_currency)
            )
        postings.append(LedgerPosting("FEE_EXPENSE", LedgerDirection.DEBIT, fee, quote_currency))
        postings.append(LedgerPosting("CASH", LedgerDirection.CREDIT, fee, quote_currency))
        metadata["gross_proceeds"] = str(gross)
        metadata["cost_released"] = str(cost_released)
        metadata["realized_pnl"] = str(realized)
    if not journal_balanced(postings):
        raise JournalUnbalanced("generated trade journal is not balanced")
    return postings, metadata


def build_derivative_trade_entries(
    *,
    side: OrderSide,
    symbol: str,
    quote_currency: str,
    price: Decimal,
    quantity: Decimal,
    fee: Decimal,
    position_quantity_before: Decimal,
    average_entry_price: Decimal | None,
    contract_size: Decimal = Decimal("1"),
    contract_multiplier: Decimal = Decimal("1"),
    reduce_only: bool = False,
) -> tuple[list[LedgerPosting], dict]:
    """Balanced PAPER linear-contract journal with signed-position metadata."""
    price, quantity, fee = D(price), D(quantity), D(fee)
    before = D(position_quantity_before)
    contract_size, contract_multiplier = D(contract_size), D(contract_multiplier)
    delta = quantity if side == OrderSide.BUY else -quantity
    if reduce_only and (before == 0 or before * delta >= 0 or abs(delta) > abs(before)):
        raise ValueError("reduce_only derivative fill would create or reverse a position")
    closing_quantity = (
        min(abs(before), quantity) if before != 0 and before * delta < 0 else Decimal("0")
    )
    realized = Decimal("0")
    if closing_quantity > 0:
        entry = D(average_entry_price or "0")
        direction = Decimal("1") if before > 0 else Decimal("-1")
        realized = (
            (price - entry)
            * closing_quantity
            * contract_size
            * contract_multiplier
            * direction
        )
    notional = price * quantity * contract_size * contract_multiplier
    postings = [
        LedgerPosting(
            f"POSITION_NOTIONAL:{symbol}", LedgerDirection.DEBIT, notional, quote_currency
        ),
        LedgerPosting(
            f"POSITION_NOTIONAL:{symbol}", LedgerDirection.CREDIT, notional, quote_currency
        ),
    ]
    if realized > 0:
        postings.extend(
            [
                LedgerPosting("CASH", LedgerDirection.DEBIT, realized, quote_currency),
                LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, realized, quote_currency),
            ]
        )
    elif realized < 0:
        postings.extend(
            [
                LedgerPosting("REALIZED_PNL", LedgerDirection.DEBIT, -realized, quote_currency),
                LedgerPosting("CASH", LedgerDirection.CREDIT, -realized, quote_currency),
            ]
        )
    if fee > 0:
        postings.extend(
            [
                LedgerPosting("FEE_EXPENSE", LedgerDirection.DEBIT, fee, quote_currency),
                LedgerPosting("CASH", LedgerDirection.CREDIT, fee, quote_currency),
            ]
        )
    metadata = {
        "symbol": symbol,
        "quote_currency": quote_currency,
        "side": side.value,
        "quantity": str(quantity),
        "price": str(price),
        "fee": str(fee),
        "instrument_type": "LINEAR_PERP",
        "contract_size": str(contract_size),
        "contract_multiplier": str(contract_multiplier),
        "reduce_only": reduce_only,
        "position_quantity_before": str(before),
        "realized_pnl": str(realized),
    }
    if not journal_balanced(postings):
        raise JournalUnbalanced("generated derivative journal is not balanced")
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
        # Idempotent write: a fill/event is settled at most once even if the
        # engine crashes after order update but before/after ledger commit.
        if fill_id or event_id:
            async with self.session_factory() as check_session:
                existing = await self._find_transaction(
                    check_session, fill_id=fill_id, event_id=event_id
                )
            if existing is not None:
                async with self.session_factory() as load_session:
                    row = (
                        await load_session.execute(
                            select(LedgerTransactionORM)
                            .options(selectinload(LedgerTransactionORM.entries))
                            .where(LedgerTransactionORM.transaction_id == existing.transaction_id)
                        )
                    ).scalar_one()
                return await _txn_to_domain(row)
        if not postings:
            raise JournalUnbalanced("ledger transaction requires at least one posting")
        if not journal_balanced(postings):
            debits = sum(
                (p.amount for p in postings if p.direction == LedgerDirection.DEBIT), Decimal("0")
            )
            credits = sum(
                (p.amount for p in postings if p.direction == LedgerDirection.CREDIT), Decimal("0")
            )
            raise JournalUnbalanced(f"journal unbalanced: debit={debits} credit={credits}")
        transaction_id = transaction_id or new_id("txn")
        created_at = created_at or datetime.now(UTC)
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

    @staticmethod
    async def _find_transaction(
        session: AsyncSession, *, fill_id: str | None = None, event_id: str | None = None
    ) -> LedgerTransactionORM | None:
        query = select(LedgerTransactionORM)
        if fill_id:
            query = query.where(LedgerTransactionORM.fill_id == fill_id)
        if event_id:
            query = query.where(LedgerTransactionORM.event_id == event_id)
        if not fill_id and not event_id:
            return None
        return (await session.execute(query)).scalars().first()

    async def list_entries_recent(self, limit: int = 200) -> list[LedgerEntry]:
        async with self.session_factory() as session:
            from crypto_trader.persistence.models import LedgerEntryORM as E

            rows = (
                (await session.execute(select(E).order_by(E.id.desc()).limit(limit)))
                .scalars()
                .all()
            )
            return [
                LedgerEntry(
                    entry_id=r.entry_id,
                    transaction_id=r.transaction_id,
                    seq=r.seq,
                    entry_type=LedgerEntryType(r.entry_type),
                    account=r.account,
                    direction=LedgerDirection(r.direction),
                    amount=r.amount,
                    currency=r.currency,
                    created_at=r.created_at,
                    order_id=r.order_id,
                    fill_id=r.fill_id,
                    event_id=r.event_id,
                    metadata=r.metadata_json or {},
                )
                for r in rows
            ]

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
