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


# Sources that only enrich evidence and must never gate core execution health.
EVIDENCE_ONLY_SOURCES: frozenset[str] = frozenset({"trades"})


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
    # --- Phase 1 V2 factual evidence extension (all defaulted, one source of truth) ---
    # Rolling per-symbol taker flow over the bounded public-trades window.
    taker_buy_volume: StrictDecimal | None = None
    taker_sell_volume: StrictDecimal | None = None
    cvd: StrictDecimal | None = None
    trade_count: int = 0
    trade_notional: StrictDecimal | None = None
    large_trade_count: int = 0
    largest_trade_notional: StrictDecimal | None = None
    trades_window_seconds: float = 0.0
    last_trade_price: StrictDecimal | None = None
    # Book microstructure facts derived from the same bounded snapshot.
    depth_bid_5: StrictDecimal = Decimal("0")
    depth_ask_5: StrictDecimal = Decimal("0")
    depth_bid_10: StrictDecimal = Decimal("0")
    depth_ask_10: StrictDecimal = Decimal("0")
    imbalance_l5: Decimal = Decimal("0")
    microprice: StrictDecimal = Decimal("0")
    spread_bps: Decimal = Decimal("0")
    # Evidence quality is separate from execution-critical core health: a
    # missing trades stream degrades evidence quality without authorizing risk.
    evidence_quality: DataHealth = DataHealth.UNAVAILABLE
    evidence_degraded_reasons: list[str] = Field(default_factory=list)
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
        self.evidence_quality = DataHealth.UNAVAILABLE
        self.evidence_degraded_reasons = [reason]
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
        self.compute_evidence_quality()

    def compute_evidence_quality(
        self,
        *,
        required_sources: tuple[str, ...] = ("ticker", "orderbook", "mark_price"),
        optional_sources: tuple[str, ...] = ("trades", "funding", "open_interest", "index_price"),
        max_optional_age_seconds: float = 60.0,
    ) -> DataHealth:
        """Derive an explicit evidence-quality verdict from factual source states.

        Core execution health stays governed by ``overall_health`` (ticker +
        orderbook). This verdict only describes evidence completeness for
        downstream models; it can never authorize a new-risk order.
        """
        reasons: list[str] = []
        core_unavailable = False
        for name in required_sources:
            status = self.sources.get(name)
            if status is None or status.status in (
                DataHealth.UNAVAILABLE,
                DataHealth.INVALID,
            ):
                core_unavailable = True
                reasons.append(f"{name.upper()}_UNAVAILABLE")
            elif status.status == DataHealth.STALE:
                reasons.append(f"{name.upper()}_STALE")
        for name in optional_sources:
            status = self.sources.get(name)
            if status is None or status.status in (
                DataHealth.UNAVAILABLE,
                DataHealth.INVALID,
            ):
                reasons.append(f"{name.upper()}_UNAVAILABLE")
            elif status.status == DataHealth.STALE:
                reasons.append(f"{name.upper()}_STALE")
            elif (
                status.age_seconds is not None
                and status.age_seconds > max_optional_age_seconds
            ):
                reasons.append(f"{name.upper()}_AGED")
        if core_unavailable:
            quality = DataHealth.UNAVAILABLE
        elif any(
            reason.endswith("_UNAVAILABLE") or reason.endswith("_STALE") for reason in reasons
        ):
            quality = DataHealth.DEGRADED
        elif reasons:
            quality = DataHealth.DEGRADED
        else:
            quality = DataHealth.HEALTHY
        self.evidence_degraded_reasons = reasons
        self.evidence_quality = quality
        return quality

    def compute_basis(self) -> None:
        if self.index_price and self.index_price > 0:
            self.basis = (self.mark_price - self.index_price) / self.index_price
        else:
            self.basis = None
        self.version += 1

    def overall_health(self) -> DataHealth:
        # Evidence-only sources (e.g. the public trades stream) never gate
        # execution-critical health; they degrade evidence_quality instead.
        statuses = [
            source.status
            for name, source in self.sources.items()
            if name not in EVIDENCE_ONLY_SOURCES
        ]
        if not statuses:
            return DataHealth.UNAVAILABLE
        if all(s == DataHealth.HEALTHY for s in statuses):
            return DataHealth.HEALTHY
        if any(s == DataHealth.STALE for s in statuses):
            return DataHealth.STALE
        return DataHealth.DEGRADED
