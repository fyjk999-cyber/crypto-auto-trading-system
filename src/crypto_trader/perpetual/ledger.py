"""Futures ledger extension and projection.

All futures money movement uses the existing append-only LedgerService and
remains journal-balanced. FuturesProjection replays those transactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
from crypto_trader.domain.money import D
from crypto_trader.ledger.service import LedgerPosting, LedgerService
from crypto_trader.perpetual.domain import MarginPosition, PerpetualContract, PositionSide
from crypto_trader.persistence.models import LedgerTransactionORM


@dataclass
class FuturesProjectionSnapshot:
    positions: dict[str, MarginPosition] = field(default_factory=dict)
    margin_balance: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    funding_paid: Decimal = Decimal("0")
    funding_received: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")


class FuturesLedger:
    def __init__(self, ledger: LedgerService) -> None:
        self.ledger = ledger

    async def margin_post(
        self, contract: PerpetualContract, amount: Decimal, *, order_id: str | None = None
    ) -> None:
        symbol = contract.symbol
        await self.ledger.record(
            LedgerEntryType.FUTURES_MARGIN_POST,
            [
                LedgerPosting(
                    f"MARGIN:{symbol}", LedgerDirection.DEBIT, amount, contract.margin_asset
                ),
                LedgerPosting("CASH", LedgerDirection.CREDIT, amount, contract.margin_asset),
            ],
            order_id=order_id,
            metadata={"symbol": symbol, "amount": str(amount)},
        )

    async def margin_release(
        self, contract: PerpetualContract, amount: Decimal, *, order_id: str | None = None
    ) -> None:
        symbol = contract.symbol
        await self.ledger.record(
            LedgerEntryType.FUTURES_MARGIN_RELEASE,
            [
                LedgerPosting("CASH", LedgerDirection.DEBIT, amount, contract.margin_asset),
                LedgerPosting(
                    f"MARGIN:{symbol}", LedgerDirection.CREDIT, amount, contract.margin_asset
                ),
            ],
            order_id=order_id,
            metadata={"symbol": symbol, "amount": str(amount)},
        )

    async def record_open(
        self,
        contract: PerpetualContract,
        side: PositionSide,
        quantity: Decimal,
        entry_price: Decimal,
        leverage: Decimal,
        initial_margin: Decimal,
        fee: Decimal,
        *,
        order_id: str | None = None,
    ) -> None:
        symbol = contract.symbol
        notional = abs(D(quantity)) * D(entry_price) * contract.contract_size
        postings = [
            LedgerPosting(
                f"FUTURES_POSITION_ASSET:{symbol}",
                LedgerDirection.DEBIT,
                notional,
                contract.margin_asset,
            ),
            LedgerPosting(
                f"FUTURES_POSITION_LIABILITY:{symbol}",
                LedgerDirection.CREDIT,
                notional,
                contract.margin_asset,
            ),
            LedgerPosting("FUTURES_TRADING_FEE", LedgerDirection.DEBIT, fee, contract.margin_asset),
            LedgerPosting("CASH", LedgerDirection.CREDIT, fee, contract.margin_asset),
            LedgerPosting(
                f"MARGIN:{symbol}", LedgerDirection.DEBIT, initial_margin, contract.margin_asset
            ),
            LedgerPosting("CASH", LedgerDirection.CREDIT, initial_margin, contract.margin_asset),
        ]
        await self.ledger.record(
            LedgerEntryType.FUTURES_TRADING_FEE if fee > 0 else LedgerEntryType.FUTURES_MARGIN_POST,
            postings,
            order_id=order_id,
            metadata={
                "symbol": symbol,
                "side": side.value,
                "quantity": str(quantity),
                "entry_price": str(entry_price),
                "leverage": str(leverage),
                "initial_margin": str(initial_margin),
                "fee": str(fee),
                "action": "OPEN",
            },
        )

    async def record_close(
        self,
        contract: PerpetualContract,
        side: PositionSide,
        quantity: Decimal,
        entry_price: Decimal,
        exit_price: Decimal,
        realized_pnl: Decimal,
        fee: Decimal,
        margin_release: Decimal,
        *,
        order_id: str | None = None,
    ) -> None:
        symbol = contract.symbol
        entry_notional = abs(D(quantity)) * D(entry_price) * contract.contract_size
        pnl = D(realized_pnl)
        postings = [
            LedgerPosting(
                f"FUTURES_POSITION_LIABILITY:{symbol}",
                LedgerDirection.DEBIT,
                entry_notional,
                contract.margin_asset,
            ),
            LedgerPosting(
                f"FUTURES_POSITION_ASSET:{symbol}",
                LedgerDirection.CREDIT,
                entry_notional,
                contract.margin_asset,
            ),
        ]
        if pnl > 0:
            postings += [
                LedgerPosting("CASH", LedgerDirection.DEBIT, pnl, contract.margin_asset),
                LedgerPosting(
                    "FUTURES_REALIZED_PNL", LedgerDirection.CREDIT, pnl, contract.margin_asset
                ),
            ]
        elif pnl < 0:
            postings += [
                LedgerPosting(
                    "FUTURES_REALIZED_PNL", LedgerDirection.DEBIT, -pnl, contract.margin_asset
                ),
                LedgerPosting("CASH", LedgerDirection.CREDIT, -pnl, contract.margin_asset),
            ]
        if fee > 0:
            postings += [
                LedgerPosting(
                    "FUTURES_TRADING_FEE", LedgerDirection.DEBIT, fee, contract.margin_asset
                ),
                LedgerPosting("CASH", LedgerDirection.CREDIT, fee, contract.margin_asset),
            ]
        if margin_release > 0:
            postings += [
                LedgerPosting("CASH", LedgerDirection.DEBIT, margin_release, contract.margin_asset),
                LedgerPosting(
                    f"MARGIN:{symbol}",
                    LedgerDirection.CREDIT,
                    margin_release,
                    contract.margin_asset,
                ),
            ]
        await self.ledger.record(
            LedgerEntryType.FUTURES_REALIZED_PNL,
            postings,
            order_id=order_id,
            metadata={
                "symbol": symbol,
                "side": side.value,
                "quantity": str(quantity),
                "entry_price": str(entry_price),
                "exit_price": str(exit_price),
                "realized_pnl": str(realized_pnl),
                "fee": str(fee),
                "margin_release": str(margin_release),
                "action": "CLOSE",
            },
        )

    async def record_funding(
        self,
        contract: PerpetualContract,
        side: PositionSide,
        amount: Decimal,
        rate: Decimal,
        notional: Decimal,
        *,
        order_id: str | None = None,
    ) -> None:
        symbol = contract.symbol
        if amount > 0:
            entry_type = LedgerEntryType.FUNDING_RECEIPT
            postings = [
                LedgerPosting("CASH", LedgerDirection.DEBIT, amount, contract.margin_asset),
                LedgerPosting(
                    "FUNDING_RECEIPT", LedgerDirection.CREDIT, amount, contract.margin_asset
                ),
            ]
        elif amount < 0:
            entry_type = LedgerEntryType.FUNDING_PAYMENT
            postings = [
                LedgerPosting(
                    "FUNDING_PAYMENT", LedgerDirection.DEBIT, -amount, contract.margin_asset
                ),
                LedgerPosting("CASH", LedgerDirection.CREDIT, -amount, contract.margin_asset),
            ]
        else:
            return
        await self.ledger.record(
            entry_type,
            postings,
            order_id=order_id,
            metadata={
                "symbol": symbol,
                "side": side.value,
                "rate": str(rate),
                "notional": str(notional),
            },
        )


async def rebuild_futures_projection(session: AsyncSession) -> FuturesProjectionSnapshot:
    result = await session.execute(
        select(LedgerTransactionORM)
        .options(selectinload(LedgerTransactionORM.entries))
        .order_by(LedgerTransactionORM.created_at, LedgerTransactionORM.transaction_id)
    )
    snap = FuturesProjectionSnapshot()
    for txn in result.scalars().all():
        _apply_txn(snap, txn)
    return snap


def _apply_txn(snap: FuturesProjectionSnapshot, txn: LedgerTransactionORM) -> None:
    meta = txn.metadata_json or {}
    symbol = meta.get("symbol")
    if not symbol:
        return
    for entry in txn.entries:
        if entry.account == "FUTURES_TRADING_FEE" or entry.account == "LIQUIDATION_FEE":
            if entry.direction == "DEBIT":
                snap.fees_paid += entry.amount
    action = meta.get("action")
    if action == "OPEN":
        side = PositionSide(meta["side"])
        pos = snap.positions.setdefault(symbol, MarginPosition(symbol=symbol))
        pos.side = side
        pos.quantity = D(meta["quantity"]) if side == PositionSide.LONG else -D(meta["quantity"])
        pos.avg_entry_price = D(meta["entry_price"])
        pos.initial_margin = D(meta["initial_margin"])
        pos.leverage = D(meta["leverage"])
        snap.margin_balance += D(meta["initial_margin"])
    elif action == "CLOSE":
        pos = snap.positions.get(symbol)
        if pos is not None:
            snap.realized_pnl += D(meta["realized_pnl"])
            snap.margin_balance = max(snap.margin_balance - D(meta["margin_release"]), D("0"))
            del snap.positions[symbol]
    elif txn.entry_type in ("FUNDING_PAYMENT", "FUNDING_RECEIPT"):
        for entry in txn.entries:
            if entry.account == "FUNDING_PAYMENT" and entry.direction == "DEBIT":
                snap.funding_paid += entry.amount
            elif entry.account == "FUNDING_RECEIPT" and entry.direction == "CREDIT":
                snap.funding_received += entry.amount
