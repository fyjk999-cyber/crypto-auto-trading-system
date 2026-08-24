"""Replayable projections derived from the ledger.

The ledger is the only source of money truth. Account/Position/PnL projections
are rebuilt by deterministic replay. Direct balance mutation is forbidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType, OrderSide
from crypto_trader.domain.money import D
from crypto_trader.persistence.models import (
    AccountProjectionORM,
    LedgerTransactionORM,
    PositionProjectionORM,
)


@dataclass
class PositionView:
    symbol: str
    base_asset: str
    quote_asset: str
    quantity: Decimal = Decimal("0")
    avg_entry_price: Decimal | None = None
    cost_basis: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")


@dataclass
class ProjectionSnapshot:
    account_id: str = "default"
    balances: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    positions: dict[str, PositionView] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_deposits: Decimal = Decimal("0")
    total_withdrawals: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    version: int = 0

    def balance(self, currency: str) -> Decimal:
        row = self.balances.get(currency)
        return row["total"] if row else Decimal("0")

    def as_plain(self) -> dict:
        return {
            "account_id": self.account_id,
            "balances": {k: {kk: str(vv) for kk, vv in v.items()} for k, v in self.balances.items()},
            "positions": {k: {
                "quantity": str(v.quantity),
                "avg_entry_price": str(v.avg_entry_price) if v.avg_entry_price is not None else None,
                "cost_basis": str(v.cost_basis),
                "realized_pnl": str(v.realized_pnl),
            } for k, v in self.positions.items()},
            "realized_pnl": str(self.realized_pnl),
            "total_fees": str(self.total_fees),
            "equity": str(self.equity),
        }


class ProjectionBuilder:
    def __init__(self, initial_balances: dict[str, Decimal] | None = None, account_id: str = "default") -> None:
        self.account_id = account_id
        self.snapshot = ProjectionSnapshot(account_id=account_id)
        for currency, amount in (initial_balances or {}).items():
            self._set_balance(currency, D(amount))

    def _set_balance(self, currency: str, total: Decimal) -> None:
        self.snapshot.balances[currency] = {"total": total, "available": total, "frozen": Decimal("0")}

    def _get_balance(self, currency: str) -> Decimal:
        return self.snapshot.balance(currency)

    def apply_transaction(self, txn: LedgerTransactionORM) -> None:
        entry_type = LedgerEntryType(txn.entry_type)
        metadata = txn.metadata_json or {}
        for entry in sorted(txn.entries, key=lambda e: e.seq):
            direction = LedgerDirection(entry.direction)
            if entry.account in ("CASH", "MARGIN") or entry.account.startswith("MARGIN:"):
                currency = entry.currency
                current = self._get_balance(currency)
                if direction == LedgerDirection.DEBIT:
                    self._set_balance(currency, current + entry.amount)
                else:
                    self._set_balance(currency, current - entry.amount)
            if entry.account == "FEE_EXPENSE" and direction == LedgerDirection.DEBIT:
                self.snapshot.total_fees += entry.amount
        if entry_type == LedgerEntryType.DEPOSIT:
            amount = D(metadata.get("amount", metadata.get("quantity", "0")))
            self.snapshot.total_deposits += amount
        elif entry_type == LedgerEntryType.WITHDRAWAL:
            amount = D(metadata.get("amount", metadata.get("quantity", "0")))
            self.snapshot.total_withdrawals += amount
        elif entry_type == LedgerEntryType.TRADE:
            self._apply_trade(metadata)

    def _apply_trade(self, metadata: dict) -> None:
        symbol = metadata["symbol"]
        side = OrderSide(metadata["side"])
        quantity = D(metadata["quantity"])
        price = D(metadata["price"])
        pos = self.snapshot.positions.get(symbol)
        if pos is None:
            pos = PositionView(
                symbol=symbol,
                base_asset=metadata.get("base_asset", symbol.replace("USDT", "")),
                quote_asset=metadata.get("quote_currency", "USDT"),
            )
            self.snapshot.positions[symbol] = pos
        gross = price * quantity
        if side == OrderSide.BUY:
            new_qty = pos.quantity + quantity
            new_cost = pos.cost_basis + gross
            pos.quantity = new_qty
            pos.cost_basis = new_cost
            pos.avg_entry_price = (new_cost / new_qty) if new_qty > 0 else None
        else:
            if pos.quantity < quantity:
                raise ValueError(f"oversell: {symbol} position {pos.quantity} < sell {quantity}")
            avg = pos.avg_entry_price or Decimal("0")
            release = avg * quantity
            pos.quantity -= quantity
            pos.cost_basis = max(pos.cost_basis - release, Decimal("0"))
            pos.realized_pnl += gross - release
            self.snapshot.realized_pnl += gross - release
            if pos.quantity == 0:
                pos.avg_entry_price = None
                pos.cost_basis = Decimal("0")
            else:
                pos.avg_entry_price = (pos.cost_basis / pos.quantity) if pos.quantity > 0 else None
        # positions don't create equity; equity is cash + cost basis of open positions
        self.snapshot.equity = self.snapshot.balance("USDT") + sum(
            (p.cost_basis for p in self.snapshot.positions.values()), Decimal("0")
        )

    def finalize(self) -> ProjectionSnapshot:
        return self.snapshot


async def replay_projections(
    session: AsyncSession,
    initial_balances: dict[str, Decimal] | None = None,
    account_id: str = "default",
) -> ProjectionSnapshot:
    result = await session.execute(
        select(LedgerTransactionORM).options(selectinload(LedgerTransactionORM.entries)).order_by(
            LedgerTransactionORM.created_at, LedgerTransactionORM.transaction_id
        )
    )
    builder = ProjectionBuilder(initial_balances=initial_balances, account_id=account_id)
    for txn in result.scalars().all():
        builder.apply_transaction(txn)
    return builder.finalize()


async def rebuild_projections(
    session: AsyncSession,
    initial_balances: dict[str, Decimal] | None = None,
    account_id: str = "default",
) -> ProjectionSnapshot:
    """Replay ledger and atomically replace persisted projection tables."""
    snapshot = await replay_projections(session, initial_balances, account_id)
    await session.execute(delete(AccountProjectionORM).where(AccountProjectionORM.account_id == account_id))
    await session.execute(delete(PositionProjectionORM).where(PositionProjectionORM.account_id == account_id))
    now = datetime.now(timezone.utc)
    for currency, row in snapshot.balances.items():
        session.add(
            AccountProjectionORM(
                account_id=account_id,
                currency=currency,
                total=row["total"],
                available=row["available"],
                frozen=row["frozen"],
                equity=snapshot.equity,
                version=snapshot.version + 1,
                updated_at=now,
            )
        )
    for pos in snapshot.positions.values():
        session.add(
            PositionProjectionORM(
                account_id=account_id,
                symbol=pos.symbol,
                base_asset=pos.base_asset,
                quote_asset=pos.quote_asset,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                cost_basis=pos.cost_basis,
                realized_pnl=pos.realized_pnl,
                updated_at=now,
            )
        )
    await session.commit()
    return snapshot
