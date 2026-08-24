from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from crypto_trader.domain.money import D, format_decimal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExactDecimal(TypeDecorator):
    """Decimal stored as canonical string to guarantee exact round-trip on SQLite and PostgreSQL."""
    impl = String(80)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("binary float forbidden in persistence layer")
        return format_decimal(D(value))

    def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
        return D(value) if value is not None else None


class Base(DeclarativeBase):
    pass


class EngineRunORM(Base):
    __tablename__ = "engine_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="STARTING")
    mode: Mapped[str] = mapped_column(String(16), default="PAPER")
    strategy_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class RuntimeLeaseORM(Base):
    __tablename__ = "runtime_leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lease_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class OrderORM(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )

    internal_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    time_in_force: Mapped[str] = mapped_column(String(8))
    price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    quantity: Mapped[Decimal] = mapped_column(ExactDecimal())
    filled_quantity: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    avg_fill_price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    status: Mapped[str] = mapped_column(String(32), index=True)
    trading_mode: Mapped[str] = mapped_column(String(16))
    strategy_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(255))
    last_event_id: Mapped[str | None] = mapped_column(String(64))

    events: Mapped[list["OrderEventORM"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderEventORM(Base):
    __tablename__ = "order_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_order_events_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.internal_order_id"), index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(64))
    exchange_order_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(40))
    status_after: Mapped[str] = mapped_column(String(32))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    order: Mapped[OrderORM] = relationship(back_populates="events")


class FillORM(Base):
    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("fill_id", name="uq_fills_fill_id"),
        UniqueConstraint("trade_id", name="uq_fills_trade_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fill_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_id: Mapped[str | None] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.internal_order_id"), index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(64))
    exchange_order_id: Mapped[str | None] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[Decimal] = mapped_column(ExactDecimal())
    quantity: Mapped[Decimal] = mapped_column(ExactDecimal())
    fee: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    fee_currency: Mapped[str | None] = mapped_column(String(16))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class TradeORM(Base):
    __tablename__ = "trades"

    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.internal_order_id"), index=True)
    fill_id: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[Decimal] = mapped_column(ExactDecimal())
    quantity: Mapped[Decimal] = mapped_column(ExactDecimal())
    fee: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    fee_currency: Mapped[str | None] = mapped_column(String(16))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerTransactionORM(Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_ledger_transactions_transaction_id"),
    )

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_type: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[str | None] = mapped_column(String(64))
    fill_id: Mapped[str | None] = mapped_column(String(64))
    event_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    entries: Mapped[list["LedgerEntryORM"]] = relationship(back_populates="transaction", cascade="all, delete-orphan")


class LedgerEntryORM(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("entry_id", name="uq_ledger_entries_entry_id"),
        Index("ix_ledger_entries_transaction_seq", "transaction_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("ledger_transactions.transaction_id"))
    seq: Mapped[int] = mapped_column(Integer)
    entry_type: Mapped[str] = mapped_column(String(32))
    account: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(ExactDecimal())
    currency: Mapped[str] = mapped_column(String(16), default="USDT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[str | None] = mapped_column(String(64))
    fill_id: Mapped[str | None] = mapped_column(String(64))
    event_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    transaction: Mapped[LedgerTransactionORM] = relationship(back_populates="entries")


class AccountProjectionORM(Base):
    __tablename__ = "accounts_projection"
    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_accounts_projection_account_currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), default="default")
    currency: Mapped[str] = mapped_column(String(16))
    total: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    available: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    frozen: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    equity: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PositionProjectionORM(Base):
    __tablename__ = "positions_projection"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uq_positions_projection_account_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), default="default")
    symbol: Mapped[str] = mapped_column(String(32))
    base_asset: Mapped[str] = mapped_column(String(16))
    quote_asset: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    avg_entry_price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    cost_basis: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketSnapshotORM(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "sequence", name="uq_market_snapshots_symbol_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    bids_json: Mapped[str] = mapped_column(String(8000))
    asks_json: Mapped[str] = mapped_column(String(8000))
    status: Mapped[str] = mapped_column(String(16))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exchange: Mapped[str] = mapped_column(String(16), default="SIM")


class ReconciliationRunORM(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    compared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16))
    local_balances_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    exchange_balances_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    positions_diff_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    alerts_json: Mapped[list[Any] | None] = mapped_column(JSON)


class RiskDecisionORM(Base):
    __tablename__ = "risk_decisions"

    risk_decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String(64))
    client_order_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(255))
    checks_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(String(64))


class AuditEventORM(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_audit_events_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_event_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32), default="engine")
    target: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str | None] = mapped_column(String(64))
    client_order_id: Mapped[str | None] = mapped_column(String(64))
    exchange_order_id: Mapped[str | None] = mapped_column(String(64))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
