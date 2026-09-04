from __future__ import annotations

from datetime import UTC, datetime
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
    return datetime.now(UTC)


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
    # epoch seconds for exact cross-database CAS comparisons
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    acquired_at: Mapped[float] = mapped_column(Float, default=lambda: datetime.now(UTC).timestamp())
    renewed_at: Mapped[float | None] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, default=1)
    fence_generation: Mapped[int] = mapped_column(Integer, default=1)


class OrderORM(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),)

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

    events: Mapped[list[OrderEventORM]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderEventORM(Base):
    __tablename__ = "order_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_order_events_event_id"),)

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

    entries: Mapped[list[LedgerEntryORM]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


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


class TradePlanORM(Base):
    """Durable entry thesis with one plan per Live-LLM decision."""

    __tablename__ = "trade_plans"
    __table_args__ = (UniqueConstraint("decision_id", name="uq_trade_plans_decision_id"),)

    trade_plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PLANNED")
    thesis: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    requested_quantity: Mapped[Decimal] = mapped_column(ExactDecimal(), nullable=False)
    requested_leverage: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    signal_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    risk_decision_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    position_symbol: Mapped[str | None] = mapped_column(String(64))
    terminal_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMDecisionORM(Base):
    """Canonical truth store for every real ChiefTrader decision attempt."""

    __tablename__ = "llm_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    position_state: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    model_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    market_regime: Mapped[str] = mapped_column(String(64), nullable=False)
    thesis: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    supporting_evidence_json: Mapped[list[Any] | None] = mapped_column(JSON)
    contradicting_evidence_json: Mapped[list[Any] | None] = mapped_column(JSON)
    tool_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    memory_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    research_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    episode_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    requested_exposure: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    requested_quantity: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    requested_leverage: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    parent_decision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    trade_plan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    position_quantity_before: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    entry_price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    mark_price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    time_in_trade_seconds: Mapped[float | None] = mapped_column(Float)
    original_trade_plan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    original_entry_decision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEventORM(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_audit_events_event_id"),)

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


class TradeMemoryRecordORM(Base):
    __tablename__ = "trade_memory_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    regime: Mapped[str] = mapped_column(String(16))
    raw_confidence: Mapped[Decimal] = mapped_column(ExactDecimal())
    calibrated_confidence: Mapped[Decimal] = mapped_column(ExactDecimal())
    recommended_position: Mapped[Decimal] = mapped_column(ExactDecimal())
    approved_position: Mapped[Decimal] = mapped_column(ExactDecimal())
    recommended_leverage: Mapped[Decimal] = mapped_column(ExactDecimal())
    approved_leverage: Mapped[Decimal] = mapped_column(ExactDecimal())
    entry: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    exit: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    mae: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    mfe: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    fees: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    funding_pnl: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    realized_pnl: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    r_multiple: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    failure_class: Mapped[str | None] = mapped_column(String(32))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyReviewRunORM(Base):
    __tablename__ = "daily_review_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_date: Mapped[str] = mapped_column(String(16), unique=True)
    daily_pnl: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    long_pnl: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    short_pnl: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    profit_factor: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    expectancy: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMStrategyCardORM(Base):
    __tablename__ = "llm_strategy_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(64))
    strategy_family: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(1000), default="")
    ideal_market_regime: Mapped[str] = mapped_column(String(32), default="")
    bad_market_regime: Mapped[str] = mapped_column(String(32), default="")
    entry_logic: Mapped[str] = mapped_column(String(1000), default="")
    exit_logic: Mapped[str] = mapped_column(String(1000), default="")
    failure_modes: Mapped[str] = mapped_column(String(1000), default="")
    required_tools: Mapped[str] = mapped_column(String(500), default="")
    historical_examples: Mapped[str] = mapped_column(String(1000), default="")
    confidence: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0.5"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AITradeEpisodeORM(Base):
    __tablename__ = "ai_trade_episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market_regime: Mapped[str] = mapped_column(String(16))
    market_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quant_evidence_json: Mapped[list[Any] | None] = mapped_column(JSON)
    strategy_selected: Mapped[str] = mapped_column(String(200), default="")
    llm_reasoning: Mapped[str] = mapped_column(String(2000), default="")
    entry_price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    exit_price: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    position_size: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    leverage: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    holding_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    mfe: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    mae: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    result: Mapped[str] = mapped_column(String(16), default="")
    review_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AITradeReviewORM(Base):
    __tablename__ = "ai_trade_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(String(64), unique=True)
    success_factors_json: Mapped[list[Any] | None] = mapped_column(JSON)
    failure_factors_json: Mapped[list[Any] | None] = mapped_column(JSON)
    mistakes_json: Mapped[list[Any] | None] = mapped_column(JSON)
    lessons_json: Mapped[list[Any] | None] = mapped_column(JSON)
    future_rules_json: Mapped[list[Any] | None] = mapped_column(JSON)
    confidence: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0.5"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIMarketPatternORM(Base):
    __tablename__ = "ai_market_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(64), unique=True)
    regime: Mapped[str] = mapped_column(String(16))
    features_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    strategy: Mapped[str] = mapped_column(String(64))
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    profit_factor: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    success_drivers_json: Mapped[list[Any] | None] = mapped_column(JSON)
    failure_drivers_json: Mapped[list[Any] | None] = mapped_column(JSON)
    confidence: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    embedding_json: Mapped[list[Any] | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AICoinProfileORM(Base):
    __tablename__ = "ai_coin_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    profile_summary: Mapped[str] = mapped_column(String(200), default="")
    behavior_tags_json: Mapped[list[Any] | None] = mapped_column(JSON)
    best_setups_json: Mapped[list[Any] | None] = mapped_column(JSON)
    worst_setups_json: Mapped[list[Any] | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AICompressedExperienceORM(Base):
    __tablename__ = "ai_compressed_experience"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(2000))
    source_episode_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShadowCampaignORM(Base):
    __tablename__ = "shadow_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String(64), unique=True)
    start_time: Mapped[str | None] = mapped_column(String(64))
    last_observation_time: Mapped[str | None] = mapped_column(String(64))
    elapsed_real_calendar_days: Mapped[float] = mapped_column(Float, default=0.0)
    valid_observation_days: Mapped[int] = mapped_column(Integer, default=0)
    decision_count: Mapped[int] = mapped_column(Integer, default=0)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    no_trade_count: Mapped[int] = mapped_column(Integer, default=0)
    symbol_coverage_json: Mapped[list[Any] | None] = mapped_column(JSON)
    regime_coverage_json: Mapped[list[Any] | None] = mapped_column(JSON)
    downtime_hours: Mapped[float] = mapped_column(Float, default=0.0)
    provider_failures: Mapped[int] = mapped_column(Integer, default=0)
    market_data_failures: Mapped[int] = mapped_column(Integer, default=0)
    critical_incidents: Mapped[int] = mapped_column(Integer, default=0)
    data_quality_score: Mapped[float] = mapped_column(Float, default=100.0)
    campaign_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CapitalAllocationORM(Base):
    __tablename__ = "capital_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    allocation_id: Mapped[str] = mapped_column(String(64), unique=True)
    decision_id: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    requested_capital_fraction: Mapped[Decimal] = mapped_column(
        ExactDecimal(), default=Decimal("0")
    )
    recommended_capital_fraction: Mapped[Decimal] = mapped_column(
        ExactDecimal(), default=Decimal("0")
    )
    recommended_notional: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    recommended_risk_budget: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    max_allowed_fraction: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    allocation_confidence: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    reason_codes_json: Mapped[list[Any] | None] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(16), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorRegistryORM(Base):
    __tablename__ = "factor_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16), default="1.0")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    description: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorValueORM(Base):
    __tablename__ = "factor_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    factor: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(16))
    value: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    confidence: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorSnapshotORM(Base):
    __tablename__ = "factor_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16))
    snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorPerformanceORM(Base):
    __tablename__ = "factor_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16))
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    average_return: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    sharpe: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    max_drawdown: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    profit_factor: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorAttributionORM(Base):
    __tablename__ = "factor_attribution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(64), index=True)
    factor_name: Mapped[str] = mapped_column(String(32))
    contribution: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    direction: Mapped[str] = mapped_column(String(8), default="positive")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorDecayORM(Base):
    __tablename__ = "factor_decay"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    old_performance: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    new_performance: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorCatalogORM(Base):
    __tablename__ = "factor_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    formula: Mapped[str] = mapped_column(String(200), default="")
    data_source: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="CANDIDATE")
    created_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketRegimeHistoryORM(Base):
    __tablename__ = "market_regime_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    regime: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_json: Mapped[list[Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorRegimePerformanceORM(Base):
    __tablename__ = "factor_regime_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    regime: Mapped[str] = mapped_column(String(32))
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    sharpe: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    return_value: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    drawdown: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorConfidenceORM(Base):
    __tablename__ = "factor_confidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    historical_reliability: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    regime_match: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    decay_penalty: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorCombinationORM(Base):
    __tablename__ = "factor_combinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    factors_json: Mapped[list[Any] | None] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(16), default="TESTING")
    status: Mapped[str] = mapped_column(String(16), default="TESTING")
    performance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketAnomalyORM(Base):
    __tablename__ = "market_anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_json: Mapped[list[Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchHypothesisORM(Base):
    __tablename__ = "research_hypothesis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(200))
    factor: Mapped[str] = mapped_column(String(32))
    logic: Mapped[str] = mapped_column(String(200), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchExperimentORM(Base):
    __tablename__ = "research_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hypothesis: Mapped[str] = mapped_column(String(200))
    dataset: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(32), default="walk_forward")
    result: Mapped[str] = mapped_column(String(16), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchReportORM(Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(64), unique=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    conclusion: Mapped[str] = mapped_column(String(500), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketIntelligenceContextORM(Base):
    __tablename__ = "market_intelligence_context"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketSimilarityCaseORM(Base):
    __tablename__ = "market_similarity_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    current_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    historical_state: Mapped[str] = mapped_column(String(64))
    similarity: Mapped[float] = mapped_column(Float, default=0.0)
    outcome: Mapped[str] = mapped_column(String(16), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchConsensusORM(Base):
    __tablename__ = "research_consensus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_ids_json: Mapped[list[Any] | None] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(String(500), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeRelationORM(Base):
    __tablename__ = "knowledge_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_a: Mapped[str] = mapped_column(String(64))
    relation: Mapped[str] = mapped_column(String(32))
    entity_b: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorLifecycleORM(Base):
    __tablename__ = "factor_lifecycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    old_state: Mapped[str] = mapped_column(String(16))
    new_state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchPriorityORM(Base):
    __tablename__ = "research_priority"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorImportanceORM(Base):
    __tablename__ = "factor_importance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    importance: Mapped[Decimal] = mapped_column(ExactDecimal(), default=Decimal("0"))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDecayORM(Base):
    __tablename__ = "knowledge_decay"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    decay_score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchFeedbackORM(Base):
    __tablename__ = "research_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    feedback_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeedbackValidationORM(Base):
    __tablename__ = "feedback_validation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegimeForecastORM(Base):
    __tablename__ = "regime_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    current_regime: Mapped[str] = mapped_column(String(32))
    probabilities_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorForecastORM(Base):
    __tablename__ = "factor_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    current_health: Mapped[str] = mapped_column(String(16))
    degrading_probability: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfidenceForecastORM(Base):
    __tablename__ = "confidence_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(64), index=True)
    valid_probability: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PredictionResultORM(Base):
    __tablename__ = "prediction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actual: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchEvolutionORM(Base):
    __tablename__ = "research_evolution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactorEvolutionORM(Base):
    __tablename__ = "factor_evolution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_name: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeEvolutionORM(Base):
    __tablename__ = "knowledge_evolution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchOptimizationORM(Base):
    __tablename__ = "research_optimization"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
