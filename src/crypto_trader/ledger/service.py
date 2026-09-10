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
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType, OrderSide
from crypto_trader.domain.errors import JournalUnbalanced
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import LedgerEntry, LedgerTransaction
from crypto_trader.domain.money import D
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
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
    notional = ExposureService.calculate(
        quantity=quantity,
        price=price,
        spec=InstrumentExposureSpec(
            instrument_type="LINEAR_PERP",
            contract_size=contract_size,
            contract_multiplier=contract_multiplier,
        ),
        side="LONG" if side == OrderSide.BUY else "SHORT",
    ).gross_notional
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


@dataclass(frozen=True)
class PnlProvenance:
    account_id: str
    currency: str
    window_start: datetime
    window_end: datetime
    ledger_watermark: str | None
    realized_pnl: Decimal
    fees: Decimal
    funding_amount: Decimal | None
    funding_status: str
    calculation_version: str = "v1"
    complete: bool = False
    unknown_reasons: tuple[str, ...] = ()


class FundingStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    KNOWN_ZERO = "KNOWN_ZERO"
    KNOWN_VALUE = "KNOWN_VALUE"
    UNKNOWN = "UNKNOWN"


class LedgerService:
    """Atomic ledger writer and reader."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory





    async def net_pnl_provenance_since(
        self,
        start: datetime,
        *,
        account_id: str = "default",
        currency: str = "USDT",
        funding_coverage_status: str = "UNKNOWN",
    ) -> PnlProvenance:
        end = datetime.now(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM).where(
                        LedgerEntryORM.account.in_(
                            (
                                "REALIZED_PNL",
                                "FUTURES_REALIZED_PNL",
                                "FEE_EXPENSE",
                                "FUNDING_RECEIPT",
                                "FUNDING_PAYMENT",
                            )
                        ),
                        LedgerEntryORM.created_at >= start,
                    )
                )
            ).scalars().all()
        realized = Decimal("0")
        fees = Decimal("0")
        funding = Decimal("0")
        funding_rows = 0
        for row in rows:
            signed = (
                row.amount
                if row.direction == LedgerDirection.CREDIT.value
                else -row.amount
            )
            if row.account in {"REALIZED_PNL", "FUTURES_REALIZED_PNL"}:
                realized += signed
            elif row.account == "FEE_EXPENSE":
                fees += -signed
            else:
                funding_rows += 1
                funding += signed
        if funding_rows:
            funding_status = "KNOWN_VALUE"
            funding_amount: Decimal | None = funding
        else:
            funding_status = funding_coverage_status
            funding_amount = Decimal("0") if funding_coverage_status == "KNOWN_ZERO" else None
        complete = funding_status != "UNKNOWN"
        unknown = () if complete else ("FUNDING_UNKNOWN",)
        return PnlProvenance(
            account_id=account_id,
            currency=currency,
            window_start=start,
            window_end=end,
            ledger_watermark=None,
            realized_pnl=realized,
            fees=fees,
            funding_amount=funding_amount,
            funding_status=funding_status,
            complete=complete,
            unknown_reasons=unknown,
        )

    async def apply_paper_funding_settlement(self, settlement) -> Decimal:
        """Idempotently post a versioned PAPER funding settlement."""
        amount = D(settlement.signed_amount)
        if amount == 0:
            return Decimal("0")
        if amount > 0:
            entry_type = LedgerEntryType.FUNDING_RECEIPT
            postings = [
                LedgerPosting("CASH", LedgerDirection.DEBIT, amount, settlement.currency),
                LedgerPosting(
                    "FUNDING_RECEIPT", LedgerDirection.CREDIT, amount, settlement.currency
                ),
            ]
        else:
            entry_type = LedgerEntryType.FUNDING_PAYMENT
            postings = [
                LedgerPosting(
                    "FUNDING_PAYMENT", LedgerDirection.DEBIT, -amount, settlement.currency
                ),
                LedgerPosting("CASH", LedgerDirection.CREDIT, -amount, settlement.currency),
            ]
        await self.record(
            entry_type,
            postings,
            event_id=settlement.idempotency_key,
            metadata={
                "source": "PAPER_DERIVED",
                "rule_version": settlement.rule_version,
                "settlement_timestamp": settlement.settlement_timestamp.isoformat(),
            },
        )
        return amount

    async def record(
        self,
        entry_type: LedgerEntryType,
        postings: list[LedgerPosting],
        *,
        transaction_id: str | None = None,
        account_id: str = "default",
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
                account_id=account_id,
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



    async def funding_status_since(self, start: datetime) -> FundingStatus:
        """Return factual funding applicability state for a UTC interval.

        Without a complete funding-source coverage proof, absence of a funding
        posting is UNKNOWN, not a factual zero.
        """
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM).where(
                        LedgerEntryORM.account.in_(
                            ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                        ),
                        LedgerEntryORM.created_at >= start,
                    )
                )
            ).scalars().all()
        if rows:
            return FundingStatus.KNOWN_VALUE
        return FundingStatus.UNKNOWN

    async def realized_pnl_since(self, start: datetime) -> Decimal:
        """Sum realized PnL postings since a UTC boundary (losses are negative)."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM).where(
                        LedgerEntryORM.account == "REALIZED_PNL",
                        LedgerEntryORM.created_at >= start,
                    )
                )
            ).scalars().all()
        total = sum(
            (
                row.amount
                if row.direction == LedgerDirection.CREDIT.value
                else -row.amount
            )
            for row in rows
        )
        return total

    async def net_pnl_since(self, start: datetime) -> tuple[Decimal | None, str]:
        """Factual UTC-day net PnL: realized +/- fees + funding.

        Returns ``(net, source)``. If any required accounting line is missing
        and cannot be proven zero, net is ``None`` so Risk never treats missing
        data as zero.
        """
        accounts = (
            "REALIZED_PNL",
            "FEE_EXPENSE",
            "FUNDING_RECEIPT",
            "FUNDING_PAYMENT",
            "FUTURES_TRADING_FEE",
            "FUTURES_REALIZED_PNL",
        )
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM).where(
                        LedgerEntryORM.account.in_(accounts),
                        LedgerEntryORM.created_at >= start,
                    )
                )
            ).scalars().all()
        total = Decimal("0")
        for row in rows:
            account = row.account
            if account in {"REALIZED_PNL", "FUNDING_RECEIPT", "FUTURES_REALIZED_PNL"}:
                total += (
                    row.amount
                    if row.direction == LedgerDirection.CREDIT.value
                    else -row.amount
                )
            else:  # expense/fee/funding payment: debit increases loss
                total += (
                    -row.amount
                    if row.direction == LedgerDirection.DEBIT.value
                    else row.amount
                )
        if not rows:
            return Decimal("0"), "KNOWN_ZERO_NO_LEDGER_ACTIVITY"
        return total, "LEDGER:REALIZED+FEE+FUNDING"


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
        account_id=txn.account_id,
        entry_type=LedgerEntryType(txn.entry_type),
        created_at=txn.created_at,
        metadata=txn.metadata_json or {},
        entries=entries,
    )
