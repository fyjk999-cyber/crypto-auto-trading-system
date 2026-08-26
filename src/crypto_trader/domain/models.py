"""Unified domain objects. Exchange-specific JSON never crosses the adapter boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.enums import (
    ExchangeEventType,
    ExecutionDecision,
    LedgerDirection,
    LedgerEntryType,
    MarketDataStatus,
    MarketType,
    OrderEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
    TradingMode,
)
from crypto_trader.domain.money import (
    Balance as BalanceValue,
)
from crypto_trader.domain.money import (
    CostBasis as CostBasisValue,
)
from crypto_trader.domain.money import (
    Fee as FeeValue,
)
from crypto_trader.domain.money import (
    Margin as MarginValue,
)
from crypto_trader.domain.money import (
    Money as MoneyValue,
)
from crypto_trader.domain.money import (
    Price as PriceValue,
)
from crypto_trader.domain.money import (
    Quantity as QuantityValue,
)


class Instrument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    base_asset: str
    quote_asset: str
    status: str = "TRADING"
    tick_size: PriceValue = Decimal("0.00000001")
    step_size: QuantityValue = Decimal("0.00000001")
    min_qty: QuantityValue = Decimal("0.00000001")
    min_notional: MoneyValue = Decimal("0.00000001")
    price_precision: int = 8
    quantity_precision: int = 8
    exchange: str = "UNKNOWN"


class TradingPair(Instrument):
    """A trading pair is an instrument on a specific exchange."""


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.GTC
    price: PriceValue | None = None
    quantity: QuantityValue
    quote_order_qty: MoneyValue | None = None
    strategy_id: str = "manual"
    run_id: str | None = None
    expires_at: datetime | None = None
    market_type: MarketType = MarketType.SPOT
    position_side: PositionSide = PositionSide.FLAT
    reduce_only: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    order_id: str
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    event_type: OrderEventType
    status_after: OrderStatus
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_order_id: str
    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    price: PriceValue | None = None
    quantity: QuantityValue
    filled_quantity: QuantityValue = Decimal("0")
    avg_fill_price: PriceValue | None = None
    status: OrderStatus = OrderStatus.CREATED
    trading_mode: TradingMode = TradingMode.PAPER
    strategy_id: str = "manual"
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    rejection_reason: str | None = None
    last_event_id: str | None = None
    market_type: MarketType = MarketType.SPOT
    position_side: PositionSide = PositionSide.FLAT
    reduce_only: bool = False

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity


class Fill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fill_id: str
    trade_id: str | None = None
    order_id: str
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    symbol: str
    side: OrderSide
    price: PriceValue
    quantity: QuantityValue
    fee: FeeValue = Decimal("0")
    fee_currency: str | None = None
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_id: str
    order_id: str
    fill_id: str
    symbol: str
    side: OrderSide
    price: PriceValue
    quantity: QuantityValue
    fee: FeeValue = Decimal("0")
    fee_currency: str | None = None
    timestamp: datetime


class Fee(BaseModel):
    amount: FeeValue = Decimal("0")
    currency: str


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    base_asset: str
    quote_asset: str
    quantity: QuantityValue = Decimal("0")
    avg_entry_price: PriceValue | None = None
    cost_basis: CostBasisValue = Decimal("0")
    realized_pnl: MoneyValue = Decimal("0")
    updated_at: datetime | None = None


class Balance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    total: BalanceValue = Decimal("0")
    available: BalanceValue = Decimal("0")
    frozen: BalanceValue = Decimal("0")


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = "default"
    mode: TradingMode = TradingMode.PAPER
    balances: dict[str, Balance] = Field(default_factory=dict)
    equity: MoneyValue = Decimal("0")
    margin_used: MarginValue = Decimal("0")
    updated_at: datetime | None = None


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    transaction_id: str
    seq: int
    entry_type: LedgerEntryType
    account: str
    direction: LedgerDirection
    amount: MoneyValue
    currency: str
    created_at: datetime
    order_id: str | None = None
    fill_id: str | None = None
    event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LedgerTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    entry_type: LedgerEntryType
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    entries: list[LedgerEntry] = Field(default_factory=list)


class RiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_decision_id: str
    order_id: str | None = None
    client_order_id: str
    symbol: str
    side: OrderSide
    decision: ExecutionDecision
    reason: str | None = None
    checks: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    run_id: str | None = None


class ExchangeEvent(BaseModel):
    """Normalized exchange event envelope."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: ExchangeEventType
    symbol: str | None = None
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class SignalIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: QuantityValue
    limit_price: PriceValue | None = None
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.GTC
    expires_at: datetime | None = None
    reason: str = ""
    run_id: str | None = None
    market_type: MarketType = MarketType.SPOT
    position_side: PositionSide = PositionSide.FLAT
    reduce_only: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    sequence: int
    bids: list[tuple[PriceValue, QuantityValue]]
    asks: list[tuple[PriceValue, QuantityValue]]
    timestamp: datetime
    status: MarketDataStatus = MarketDataStatus.HEALTHY
