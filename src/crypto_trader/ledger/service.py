"""Append-only double-entry ledger.

PORTED from the reference v2 ledger module:
- atomic multi-entry journals
- debits == credits invariant before persistence
- no direct account balance mutation

Ported as semantics in Python/SQLAlchemy; reference-specific paper settlement
legs were replaced by crypto spot trade journals defined in SPAC section 6.
"""

from __future__ import annotations

from collections.abc import Mapping
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


def _pnl_signed_amount(entry: LedgerEntryORM) -> Decimal:
    """Signed PnL contribution: credit increases PnL, debit decreases it."""
    if entry.direction == LedgerDirection.CREDIT.value:
        return Decimal(entry.amount)
    return -Decimal(entry.amount)


@dataclass(frozen=True)
class FundingScope:
    """Formal funding/PnL ownership window.

    Every factual funding query must bind all five dimensions. Missing or
    mismatched identity makes the result ACCOUNTING_INCOMPLETE, never zero.
    """

    account_id: str
    currency: str
    instrument_id: str
    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        if not self.account_id or not str(self.account_id).strip():
            raise ValueError("FundingScope.account_id is required")
        if not self.currency or not str(self.currency).strip():
            raise ValueError("FundingScope.currency is required")
        if not self.instrument_id or not str(self.instrument_id).strip():
            raise ValueError("FundingScope.instrument_id is required")
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("FundingScope window must be timezone-aware UTC")
        if self.window_start >= self.window_end:
            raise ValueError("FundingScope.window_start must be before window_end")


@dataclass(frozen=True)
class FundingScopeProvenance:
    """Per account/currency/instrument proven funding result."""

    scope: FundingScope
    coverage_status: str
    settled_amount: Decimal | None
    known_subtotal: Decimal | None
    posting_count: int
    complete: bool
    unknown_reasons: tuple[str, ...] = ()


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
    known_funding_subtotal: Decimal | None = None
    required_instruments: tuple[str, ...] = ()
    scope_provenances: tuple[FundingScopeProvenance, ...] = ()


class FundingStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    KNOWN_ZERO = "KNOWN_ZERO"
    KNOWN_VALUE = "KNOWN_VALUE"
    UNKNOWN = "UNKNOWN"
    ACCOUNTING_INCOMPLETE = "ACCOUNTING_INCOMPLETE"


OWNERSHIP_VERIFIED = "VERIFIED"
OWNERSHIP_UNKNOWN = "UNKNOWN"
FUNDING_ACCOUNTS = ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
REALIZED_PNL_ACCOUNTS = ("REALIZED_PNL", "FUTURES_REALIZED_PNL")
FEE_ACCOUNTS = ("FEE_EXPENSE", "FUTURES_TRADING_FEE")
PNL_ACCOUNTS = REALIZED_PNL_ACCOUNTS + FEE_ACCOUNTS + FUNDING_ACCOUNTS


class LedgerService:
    """Atomic ledger writer and reader."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    # ------------------------------------------------------------ scoped read

    async def funding_scope_provenance(
        self, scope: FundingScope, *, coverage_status: str
    ) -> FundingScopeProvenance:
        """Prove funding for one account/currency/instrument/window.

        Postings are only counted when the transaction carries canonical
        ownership (``VERIFIED``), the exact account, the exact instrument and
        the exact currency. Any coverage status other than KNOWN_ZERO or
        KNOWN_VALUE is not a factual zero.
        """
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM)
                    .join(
                        LedgerTransactionORM,
                        LedgerTransactionORM.transaction_id
                        == LedgerEntryORM.transaction_id,
                    )
                    .where(
                        LedgerTransactionORM.ownership_status == OWNERSHIP_VERIFIED,
                        LedgerTransactionORM.account_id == scope.account_id,
                        LedgerTransactionORM.instrument_id == scope.instrument_id,
                        LedgerEntryORM.currency == scope.currency,
                        LedgerEntryORM.account.in_(FUNDING_ACCOUNTS),
                        LedgerEntryORM.created_at >= scope.window_start,
                        LedgerEntryORM.created_at < scope.window_end,
                    )
                )
            ).scalars().all()
        settled = sum((_pnl_signed_amount(row) for row in rows), Decimal("0"))
        known_subtotal = settled
        reasons: list[str] = []
        coverage = str(coverage_status or FundingStatus.UNKNOWN.value)
        if coverage not in {
            FundingStatus.KNOWN_ZERO.value,
            FundingStatus.KNOWN_VALUE.value,
        }:
            reasons.append(f"FUNDING_COVERAGE_UNKNOWN:{scope.instrument_id}")
        elif coverage == FundingStatus.KNOWN_ZERO.value and settled != 0:
            reasons.append(
                f"FUNDING_COVERAGE_CONTRADICTION:{scope.instrument_id}"
            )
        elif coverage == FundingStatus.KNOWN_VALUE.value and not rows:
            reasons.append(f"FUNDING_EVENTS_NOT_SETTLED:{scope.instrument_id}")
        complete = not reasons
        return FundingScopeProvenance(
            scope=scope,
            coverage_status=coverage,
            settled_amount=settled if complete else None,
            known_subtotal=known_subtotal,
            posting_count=len(rows),
            complete=complete,
            unknown_reasons=tuple(reasons),
        )

    async def net_pnl_provenance_since(
        self,
        start: datetime,
        *,
        account_id: str,
        currency: str,
        instrument_ids,
        end: datetime | None = None,
        coverage_status_by_instrument: dict[str, str] | None = None,
        instrument_window_starts: Mapping[str, datetime] | None = None,
    ) -> PnlProvenance:
        """Scoped UTC-window PnL provenance.

        ``instrument_ids`` is the set of instruments that must be covered
        (normally the open positions). Instruments with factual funding/PnL
        postings in the window are added automatically so a wrong instrument
        can never be silently dropped from a daily total.
        """
        if not account_id or not str(account_id).strip():
            raise ValueError("account_id is required for scoped PnL")
        if not currency or not str(currency).strip():
            raise ValueError("currency is required for scoped PnL")
        end = end or datetime.now(UTC)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("PnlProvenance window must be timezone-aware UTC")
        if start >= end:
            raise ValueError("start must be before end")
        requested = tuple(
            dict.fromkeys(
                str(instrument) for instrument in (instrument_ids or []) if instrument
            )
        )
        coverage_map = dict(coverage_status_by_instrument or {})
        window_starts = {
            str(instrument): window_start
            for instrument, window_start in (instrument_window_starts or {}).items()
        }

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM, LedgerTransactionORM)
                    .join(
                        LedgerTransactionORM,
                        LedgerTransactionORM.transaction_id
                        == LedgerEntryORM.transaction_id,
                    )
                    .where(
                        LedgerEntryORM.currency == currency,
                        LedgerEntryORM.account.in_(PNL_ACCOUNTS),
                        LedgerEntryORM.created_at >= start,
                        LedgerEntryORM.created_at < end,
                    )
                )
            ).all()

        unattributed_reasons: set[str] = set()
        realized = Decimal("0")
        fees = Decimal("0")
        known_funding = Decimal("0")
        discovered_funding_instruments: set[str] = set()
        discovered_activity_instruments: set[str] = set()
        watermark_values: list[datetime] = []
        for entry, txn in rows:
            ownership_verified = (
                txn.ownership_status == OWNERSHIP_VERIFIED and txn.account_id is not None
            )
            if not ownership_verified:
                # The retained account label on an unverified row is only an
                # unproven claim. It may affect ANY account, so every scoped
                # query must fail closed instead of trusting it.
                unattributed_reasons.add("UNATTRIBUTED_LEDGER_OWNERSHIP")
                continue
            if txn.account_id != account_id:
                continue
            if txn.created_at is not None:
                watermark_values.append(txn.created_at)
            signed = _pnl_signed_amount(entry)
            if entry.account in REALIZED_PNL_ACCOUNTS:
                realized += signed
                # A closed swap with realized activity still requires proven
                # funding coverage for the window, not just current positions.
                if txn.instrument_id:
                    discovered_activity_instruments.add(txn.instrument_id)
            elif entry.account in FEE_ACCOUNTS:
                fees += -signed
                if txn.instrument_id:
                    discovered_activity_instruments.add(txn.instrument_id)
            else:
                if not txn.instrument_id:
                    unattributed_reasons.add("FUNDING_INSTRUMENT_UNKNOWN")
                    continue
                discovered_funding_instruments.add(txn.instrument_id)
                known_funding += signed

        required = sorted(
            set(requested)
            | discovered_funding_instruments
            | discovered_activity_instruments
        )
        scope_provenances: list[FundingScopeProvenance] = []
        for instrument in required:
            raw_start = window_starts.get(instrument)
            scope_start = start
            if raw_start is not None:
                if raw_start.tzinfo is None:
                    raw_start = raw_start.replace(tzinfo=UTC)
                scope_start = max(start, raw_start)
            scope = FundingScope(
                account_id=account_id,
                currency=currency,
                instrument_id=instrument,
                window_start=scope_start,
                window_end=end,
            )
            scope_provenances.append(
                await self.funding_scope_provenance(
                    scope,
                    coverage_status=coverage_map.get(instrument, "UNKNOWN"),
                )
            )

        unknown_reasons = set(unattributed_reasons)
        for scope_prov in scope_provenances:
            unknown_reasons.update(scope_prov.unknown_reasons)
        complete = not unknown_reasons and all(
            scope_prov.complete for scope_prov in scope_provenances
        )
        if not required and not unattributed_reasons:
            funding_status = FundingStatus.NOT_APPLICABLE.value
        elif not complete:
            funding_status = FundingStatus.ACCOUNTING_INCOMPLETE.value
        elif any(
            scope_prov.coverage_status == FundingStatus.KNOWN_VALUE.value
            for scope_prov in scope_provenances
        ) or known_funding != 0:
            funding_status = FundingStatus.KNOWN_VALUE.value
        else:
            funding_status = FundingStatus.KNOWN_ZERO.value
        funding_amount = sum(
            (scope_prov.settled_amount or Decimal("0") for scope_prov in scope_provenances),
            Decimal("0"),
        ) if complete else None
        ledger_watermark = (
            max(watermark_values).isoformat() if watermark_values else None
        )
        return PnlProvenance(
            account_id=account_id,
            currency=currency,
            window_start=start,
            window_end=end,
            ledger_watermark=ledger_watermark,
            realized_pnl=realized,
            fees=fees,
            funding_amount=funding_amount,
            funding_status=funding_status,
            complete=complete,
            unknown_reasons=tuple(sorted(unknown_reasons)),
            known_funding_subtotal=known_funding if required else None,
            required_instruments=tuple(required),
            scope_provenances=tuple(scope_provenances),
        )

    async def apply_paper_funding_settlement(self, settlement) -> Decimal:
        """Idempotently post a versioned PAPER funding settlement."""
        from crypto_trader.perpetual.funding_settlement import (
            canonical_utc_timestamp,
            canonical_utc_timestamp_text,
        )

        amount = D(settlement.signed_amount)
        if amount == 0:
            return Decimal("0")
        canonical_timestamp = canonical_utc_timestamp(settlement.settlement_timestamp)
        account_id = getattr(settlement, "account_id", None) or None
        instrument_id = getattr(settlement, "instrument_id", None)
        if account_id and instrument_id:
            # Do not trust a caller-built key: the canonical business identity
            # is account|instrument|UTC instant (rule_version excluded).
            event_id = (
                f"{account_id}|{instrument_id}|"
                f"{canonical_utc_timestamp_text(canonical_timestamp)}"
            )
        else:
            event_id = settlement.idempotency_key
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
            account_id=account_id,
            instrument_id=instrument_id,
            event_id=event_id,
            # The posting is dated at the economic settlement instant, not at
            # process wall-clock time, so [start, end) window scoping is factual.
            created_at=canonical_timestamp,
            metadata={
                "source": "PAPER_DERIVED",
                "rule_version": settlement.rule_version,
                "instrument_id": instrument_id,
                "currency": settlement.currency,
                "settlement_timestamp": canonical_utc_timestamp_text(
                    canonical_timestamp
                ),
            },
        )
        return amount

    async def record(
        self,
        entry_type: LedgerEntryType,
        postings: list[LedgerPosting],
        *,
        transaction_id: str | None = None,
        account_id: str | None = None,
        instrument_id: str | None = None,
        ownership_status: str | None = None,
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
        if ownership_status is None:
            ownership_status = OWNERSHIP_VERIFIED if account_id else OWNERSHIP_UNKNOWN
        if ownership_status not in {OWNERSHIP_VERIFIED, OWNERSHIP_UNKNOWN}:
            raise ValueError(f"invalid ownership_status: {ownership_status}")
        if ownership_status == OWNERSHIP_VERIFIED and not account_id:
            # A verifier cannot certify ownership of an unknown account.
            raise ValueError("account_id is required for VERIFIED ledger ownership")
        if ownership_status == OWNERSHIP_UNKNOWN:
            # An unverified writer must not present an account claim as fact.
            # The raw value is retained only in metadata for audit.
            metadata = {
                **(metadata or {}),
                "unverified_account_claim": account_id,
            }
            account_id = None
        resolved_instrument = instrument_id or (metadata or {}).get("instrument_id")
        async with self.session_factory() as session:
            txn = LedgerTransactionORM(
                transaction_id=transaction_id,
                account_id=account_id,
                instrument_id=resolved_instrument,
                ownership_status=ownership_status,
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

    async def watermark(self, *, account_id: str, currency: str) -> str | None:
        """Canonical ledger watermark for one verified account/currency.

        Used by ValuationBatch so Sizing/Risk/API can reference the same
        factual ledger state instead of an implicit "latest" read.
        """
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(LedgerTransactionORM.created_at, LedgerEntryORM.id)
                    .join(
                        LedgerTransactionORM,
                        LedgerTransactionORM.transaction_id
                        == LedgerEntryORM.transaction_id,
                    )
                    .where(
                        LedgerTransactionORM.ownership_status == OWNERSHIP_VERIFIED,
                        LedgerTransactionORM.account_id == account_id,
                        LedgerEntryORM.currency == currency,
                    )
                    .order_by(
                        LedgerTransactionORM.created_at.desc(),
                        LedgerEntryORM.id.desc(),
                    )
                    .limit(1)
                )
            ).first()
        if row is None:
            return None
        created_at, entry_id = row
        stamp = (
            created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
        )
        return f"ledger-{stamp}-{entry_id}"

    async def funding_status_since(
        self,
        start: datetime,
        *,
        account_id: str,
        currency: str,
        instrument_id: str,
        end: datetime | None = None,
        coverage_status: str = "UNKNOWN",
    ) -> FundingStatus:
        """Scoped funding applicability for one account/currency/instrument.

        The old boundary-free call is intentionally gone: without an explicit
        scope, absence of a posting can never be a factual zero.
        """
        end = end or datetime.now(UTC)
        provenance = await self.funding_scope_provenance(
            FundingScope(
                account_id=account_id,
                currency=currency,
                instrument_id=instrument_id,
                window_start=start,
                window_end=end,
            ),
            coverage_status=coverage_status,
        )
        if not provenance.complete:
            return FundingStatus.ACCOUNTING_INCOMPLETE
        if (
            provenance.coverage_status == FundingStatus.KNOWN_VALUE.value
            or (provenance.settled_amount or Decimal("0")) != 0
        ):
            return FundingStatus.KNOWN_VALUE
        return FundingStatus.KNOWN_ZERO

    async def realized_pnl_since(
        self,
        start: datetime,
        *,
        account_id: str,
        currency: str,
        end: datetime | None = None,
    ) -> Decimal:
        """Sum verified-ownership realized PnL for one account/currency/window."""
        end = end or datetime.now(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LedgerEntryORM)
                    .join(
                        LedgerTransactionORM,
                        LedgerTransactionORM.transaction_id
                        == LedgerEntryORM.transaction_id,
                    )
                    .where(
                        LedgerTransactionORM.ownership_status == OWNERSHIP_VERIFIED,
                        LedgerTransactionORM.account_id == account_id,
                        LedgerEntryORM.currency == currency,
                        LedgerEntryORM.account == "REALIZED_PNL",
                        LedgerEntryORM.created_at >= start,
                        LedgerEntryORM.created_at < end,
                    )
                )
            ).scalars().all()
        return sum((_pnl_signed_amount(row) for row in rows), Decimal("0"))

    async def net_pnl_since(
        self,
        start: datetime,
        *,
        account_id: str,
        currency: str,
        instrument_ids=(),
        end: datetime | None = None,
        coverage_status_by_instrument: dict[str, str] | None = None,
    ) -> tuple[Decimal | None, str]:
        """Scoped factual net PnL: realized - fees + proven funding.

        Returns ``(net, source)``. If any required accounting line is missing
        and cannot be proven, net is ``None`` so Risk never treats missing data
        as zero.
        """
        provenance = await self.net_pnl_provenance_since(
            start,
            account_id=account_id,
            currency=currency,
            instrument_ids=instrument_ids,
            end=end,
            coverage_status_by_instrument=coverage_status_by_instrument,
        )
        if not provenance.complete:
            return None, provenance.funding_status
        net = (
            provenance.realized_pnl
            - provenance.fees
            + (provenance.funding_amount or Decimal("0"))
        )
        return net, "LEDGER:REALIZED-FEE+FUNDING"

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
