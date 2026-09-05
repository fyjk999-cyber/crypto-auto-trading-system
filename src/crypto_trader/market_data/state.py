"""Normalized MarketState with per-source health."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.money import StrictDecimal


class DataHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = "BINANCE_USDM_PUBLIC"
    status: DataHealth = DataHealth.UNAVAILABLE
    age_seconds: float = -1.0
    updated_at: datetime | None = None
    last_error: str | None = None
    data_source: str = "BINANCE_USDM_PUBLIC"


class MarketState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    provider: str = "BINANCE_USDM_PUBLIC"
    data_source: str = "REAL"
    instrument_id: str | None = None
    instrument_type: str = "SWAP"
    status: DataHealth = DataHealth.UNAVAILABLE
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    price: StrictDecimal = Decimal("0")
    mark_price: StrictDecimal = Decimal("0")
    index_price: StrictDecimal = Decimal("0")
    best_bid: StrictDecimal = Decimal("0")
    best_ask: StrictDecimal = Decimal("0")
    spread: StrictDecimal = Decimal("0")
    depth: Decimal = Decimal("0")
    imbalance: Decimal = Decimal("0")
    trade_volume: StrictDecimal = Decimal("0")
    volume: StrictDecimal = Decimal("0")
    funding_rate: StrictDecimal | None = None
    next_funding_time: datetime | None = None
    open_interest: StrictDecimal | None = None
    open_interest_change: StrictDecimal | None = None
    basis: StrictDecimal | None = None
    realized_volatility: StrictDecimal | None = None
    source: str = "BINANCE_USDM_PUBLIC"
    exchange: str = "BINANCE"
    exchange_timestamp: datetime | None = None
    received_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    freshness: DataHealth = DataHealth.UNAVAILABLE
    health: DataHealth = DataHealth.UNAVAILABLE
    version: int = 0
    sources: dict[str, SourceStatus] = Field(default_factory=dict)
    generation: int = 0
    new_risk_allowed: bool = False
    new_risk_block_reason: str = "MARKET_STATE_NO_GENERATION"

    def invalidate(self, reason: str = "PROVIDER_FAILURE") -> None:
        self.generation += 1
        self.health = DataHealth.UNAVAILABLE
        self.freshness = DataHealth.UNAVAILABLE
        self.new_risk_allowed = False
        self.new_risk_block_reason = reason
        for source in self.sources.values():
            source.status = DataHealth.UNAVAILABLE
            source.updated_at = None

    def mark_healthy_from_sources(self) -> None:
        self.health = self.overall_health()
        self.status = self.health
        self.freshness = self.health
        self.new_risk_allowed = self.health == DataHealth.HEALTHY
        self.new_risk_block_reason = (
            "MARKET_DATA_HEALTHY" if self.new_risk_allowed else self.health.value
        )

    def compute_basis(self) -> None:
        if self.index_price and self.index_price > 0:
            self.basis = (self.mark_price - self.index_price) / self.index_price
        else:
            self.basis = None
        self.version += 1

    def overall_health(self) -> DataHealth:
        statuses = [s.status for s in self.sources.values()]
        if not statuses:
            return DataHealth.UNAVAILABLE
        if all(s == DataHealth.HEALTHY for s in statuses):
            return DataHealth.HEALTHY
        if any(s == DataHealth.STALE for s in statuses):
            return DataHealth.STALE
        return DataHealth.DEGRADED
