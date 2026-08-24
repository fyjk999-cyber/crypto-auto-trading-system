"""Perpetual futures domain. Decimal-only, exchange-agnostic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.money import StrictDecimal


class ContractType(str, Enum):
    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"


class MarginMode(str, Enum):
    ISOLATED = "ISOLATED"
    CROSS = "CROSS"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class PerpetualContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    instrument_type: ContractType = ContractType.PERPETUAL
    base: str
    quote: str
    settlement_asset: str
    contract_size: StrictDecimal = Decimal("1")
    tick_size: StrictDecimal = Decimal("0.01")
    quantity_step: StrictDecimal = Decimal("0.001")
    margin_asset: str = "USDT"
    max_leverage: StrictDecimal = Decimal("6")
    maker_fee_rate: StrictDecimal = Decimal("0.0002")
    taker_fee_rate: StrictDecimal = Decimal("0.0005")
    funding_interval_hours: StrictDecimal = Decimal("8")


class Leverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal = Decimal("1")
    authority: str = "alpha"
    reason: str = ""
    policy_version: str = "0"


class InitialMargin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: StrictDecimal
    rate: StrictDecimal
    notional: StrictDecimal
    leverage: StrictDecimal


class MaintenanceMargin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: StrictDecimal
    rate: StrictDecimal
    notional: StrictDecimal


class MarginBalance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: StrictDecimal = Decimal("0")
    available: StrictDecimal = Decimal("0")
    used: StrictDecimal = Decimal("0")
    unrealized_pnl: StrictDecimal = Decimal("0")


class MarginRatio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal
    healthy: bool


class MarkPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal
    index_price: StrictDecimal
    basis: StrictDecimal = Decimal("0")
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LiquidationPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal
    side: PositionSide
    margin_mode: MarginMode
    distance_pct: StrictDecimal


class FundingRate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal
    next_funding_time: datetime | None = None


class FundingPayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    position_side: PositionSide
    amount: StrictDecimal
    rate: StrictDecimal
    notional: StrictDecimal
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RealizedPnl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal
    symbol: str
    side: PositionSide
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UnrealizedPnl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictDecimal
    symbol: str
    side: PositionSide
    mark_price: StrictDecimal


class MarginPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: PositionSide = PositionSide.FLAT
    quantity: Decimal = Decimal("0")
    avg_entry_price: StrictDecimal = Decimal("0")
    leverage: StrictDecimal = Decimal("1")
    margin_mode: MarginMode = MarginMode.ISOLATED
    initial_margin: Decimal = Decimal("0")
    maintenance_margin: Decimal = Decimal("0")
    mark_price: StrictDecimal = Decimal("0")
    liquidation_price: StrictDecimal | None = None
    unrealized_pnl: StrictDecimal = Decimal("0")
    realized_pnl: StrictDecimal = Decimal("0")
    funding_paid: StrictDecimal = Decimal("0")
    funding_received: StrictDecimal = Decimal("0")
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_flat(self) -> bool:
        return self.side == PositionSide.FLAT or self.quantity == 0

    def notional(self) -> Decimal:
        return abs(self.quantity) * self.avg_entry_price
