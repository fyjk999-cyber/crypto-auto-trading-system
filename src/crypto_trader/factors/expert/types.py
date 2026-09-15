"""Canonical 25-model expert evidence contract (Low-Risk V2 Phase 2).

This module extends the existing ``crypto_trader.factors`` subsystem; it is not
a parallel evidence store. Every expert output is a factual, versioned
``ModelEvidence`` record carrying support, counter and neutral evidence so the
Core LLM always sees the raw opposition. Nothing here can create or size an
order; consensus is explicitly ``NOT_AN_ORDER``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ModelFamily(StrEnum):
    TREND = "TREND"
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    VOLATILITY = "VOLATILITY"
    VOLUME_FLOW = "VOLUME_FLOW"
    ORDER_FLOW = "ORDER_FLOW"
    POSITIONING = "POSITIONING"
    REGIME = "REGIME"
    META = "META"


class EvidenceDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceQuality(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ReliabilityTier(StrEnum):
    UNVALIDATED = "UNVALIDATED"
    PROVISIONAL = "PROVISIONAL"
    EMERGING = "EMERGING"
    CANDIDATE = "CANDIDATE"
    FORMAL_VALIDATION = "FORMAL_VALIDATION"


# Initial engineering sample tiers (SPEC §Phase 5; configurable, not law).
RELIABILITY_TIERS: tuple[tuple[int, ReliabilityTier], ...] = (
    (100, ReliabilityTier.FORMAL_VALIDATION),
    (50, ReliabilityTier.CANDIDATE),
    (20, ReliabilityTier.EMERGING),
)


def reliability_for_samples(sample_size: int) -> ReliabilityTier:
    for threshold, tier in RELIABILITY_TIERS:
        if sample_size >= threshold:
            return tier
    return ReliabilityTier.PROVISIONAL if sample_size > 0 else ReliabilityTier.UNVALIDATED


@dataclass(slots=True)
class ModelSpec:
    model_id: str
    name: str
    family: ModelFamily
    version: str
    timeframes: tuple[str, ...]
    description: str


# The frozen 25-model set (SPEC §Phase 2). Order is contractual.
REQUIRED_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "01_EMA_MULTI_TF",
        "EMA Multi-TF",
        ModelFamily.TREND,
        "1.0",
        ("4h", "1h", "15m"),
        "EMA 20/50/200 structure per timeframe",
    ),
    ModelSpec(
        "02_MACD",
        "MACD",
        ModelFamily.MOMENTUM,
        "1.0",
        ("1h", "15m"),
        "MACD 12/26/9 histogram and acceleration",
    ),
    ModelSpec("03_ADX_DI", "ADX+DI", ModelFamily.TREND, "1.0", ("1h",), "ADX/DI 14 trend strength"),
    ModelSpec(
        "04_RSI_CONTEXT",
        "RSI Context",
        ModelFamily.MOMENTUM,
        "1.0",
        ("15m", "1h"),
        "RSI 14 regime-aware context",
    ),
    ModelSpec(
        "05_BOLLINGER_REGIME",
        "Bollinger Regime",
        ModelFamily.VOLATILITY,
        "1.0",
        ("1h",),
        "Bollinger 20/2σ regime and %B",
    ),
    ModelSpec(
        "06_VWAP_DEVIATION",
        "VWAP Deviation",
        ModelFamily.MEAN_REVERSION,
        "1.0",
        ("1h", "15m"),
        "rolling/session VWAP deviation",
    ),
    ModelSpec(
        "07_ATR_NATR",
        "ATR/NATR",
        ModelFamily.VOLATILITY,
        "1.0",
        ("1h", "15m"),
        "ATR 14 and normalized ATR",
    ),
    ModelSpec(
        "08_VOLUME_BREAKOUT",
        "Volume Breakout",
        ModelFamily.VOLUME_FLOW,
        "1.0",
        ("15m",),
        "relative volume + range breakout",
    ),
    ModelSpec(
        "09_CVD_TAKER_FLOW",
        "CVD/Taker Flow",
        ModelFamily.ORDER_FLOW,
        "1.0",
        ("LIVE",),
        "taker buy/sell volume and CVD",
    ),
    ModelSpec(
        "10_PRICE_OI",
        "Price+OI",
        ModelFamily.POSITIONING,
        "1.0",
        ("LIVE", "15m"),
        "price/OI change divergence",
    ),
    ModelSpec(
        "11_SMA_STRUCTURE",
        "SMA Structure",
        ModelFamily.TREND,
        "1.0",
        ("4h", "1h"),
        "SMA 20/50/200 alignment",
    ),
    ModelSpec(
        "12_SUPERTREND", "SuperTrend", ModelFamily.TREND, "1.0", ("1h", "15m"), "SuperTrend ATR10×3"
    ),
    ModelSpec(
        "13_STOCH_RSI",
        "Stochastic RSI",
        ModelFamily.MOMENTUM,
        "1.0",
        ("15m",),
        "StochRSI 14/14/3/3",
    ),
    ModelSpec("14_ROC", "ROC", ModelFamily.MOMENTUM, "1.0", ("1h", "15m"), "rate of change 12"),
    ModelSpec("15_CCI", "CCI", ModelFamily.MOMENTUM, "1.0", ("15m",), "CCI 20"),
    ModelSpec(
        "16_PRICE_ZSCORE",
        "Price Z-Score",
        ModelFamily.MEAN_REVERSION,
        "1.0",
        ("1h", "15m"),
        "z-score vs SMA 50/100",
    ),
    ModelSpec(
        "17_SUPPORT_RESISTANCE",
        "Support/Resistance",
        ModelFamily.MEAN_REVERSION,
        "1.0",
        ("1h", "15m"),
        "swing + volume-profile levels",
    ),
    ModelSpec(
        "18_OBV",
        "OBV",
        ModelFamily.VOLUME_FLOW,
        "1.0",
        ("15m",),
        "on-balance volume slope/divergence",
    ),
    ModelSpec("19_MFI", "MFI14", ModelFamily.VOLUME_FLOW, "1.0", ("15m",), "money flow index 14"),
    ModelSpec("20_CMF", "CMF20", ModelFamily.VOLUME_FLOW, "1.0", ("15m",), "Chaikin money flow 20"),
    ModelSpec(
        "21_ORDER_FLOW_ML",
        "Order Flow ML",
        ModelFamily.ORDER_FLOW,
        "0.1-proxy",
        ("LIVE", "15m"),
        "P(future return > cost) order-flow proxy",
    ),
    ModelSpec(
        "22_ORDERBOOK_IMBALANCE",
        "Order Book Imbalance",
        ModelFamily.ORDER_FLOW,
        "1.0",
        ("LIVE",),
        "L1/L5/L10 imbalance, microprice, spread",
    ),
    ModelSpec(
        "23_FUNDING_BASIS",
        "Funding+Basis",
        ModelFamily.POSITIONING,
        "1.0",
        ("LIVE",),
        "funding/basis crowding context",
    ),
    ModelSpec(
        "24_MARKET_REGIME",
        "Market Regime",
        ModelFamily.REGIME,
        "1.0",
        ("1h", "15m"),
        "trend/range/breakout/high-vol/liquidation/uncertain",
    ),
    ModelSpec(
        "25_META_FORECAST",
        "Meta Forecast",
        ModelFamily.META,
        "0.1-proxy",
        ("MULTI",),
        "restrained P(NetReturn > MinimumEdge) proxy",
    ),
)

REQUIRED_MODEL_IDS: tuple[str, ...] = tuple(spec.model_id for spec in REQUIRED_MODELS)

REGIME_LABELS = (
    "TREND_UP",
    "TREND_DOWN",
    "RANGE",
    "BREAKOUT_EXPANSION",
    "HIGH_VOLATILITY",
    "LIQUIDATION_DISLOCATION",
    "UNCERTAIN",
)


@dataclass(slots=True)
class ModelEvidence:
    """One factual expert-model output. Evidence only; never an order intent."""

    model_id: str
    model_version: str
    family: ModelFamily
    symbol: str
    timeframes: tuple[str, ...]
    direction: EvidenceDirection
    direction_score: float  # [-1, 1], positive = LONG
    confidence: float  # [0, 1]
    theory: str
    supporting_evidence: list[str] = field(default_factory=list)
    counter_evidence: list[str] = field(default_factory=list)
    neutral_evidence: list[str] = field(default_factory=list)
    regime_compatibility: list[str] = field(default_factory=list)
    strategy_compatibility: list[str] = field(default_factory=list)
    entry_use: str = ""
    exit_use: str = ""
    reassessment_use: str = ""
    invalidation: str = ""
    data_quality: EvidenceQuality = EvidenceQuality.UNAVAILABLE
    freshness_seconds: float | None = None
    sample_size: int = 0
    reliability_tier: ReliabilityTier = ReliabilityTier.UNVALIDATED
    metrics: dict[str, Any] = field(default_factory=dict)
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.direction != EvidenceDirection.UNAVAILABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "family": self.family.value,
            "symbol": self.symbol,
            "timeframes": list(self.timeframes),
            "direction": self.direction.value,
            "direction_score": round(self.direction_score, 6),
            "confidence": round(self.confidence, 6),
            "theory": self.theory,
            "supporting_evidence": list(self.supporting_evidence),
            "counter_evidence": list(self.counter_evidence),
            "neutral_evidence": list(self.neutral_evidence),
            "regime_compatibility": list(self.regime_compatibility),
            "strategy_compatibility": list(self.strategy_compatibility),
            "entry_use": self.entry_use,
            "exit_use": self.exit_use,
            "reassessment_use": self.reassessment_use,
            "invalidation": self.invalidation,
            "data_quality": self.data_quality.value,
            "freshness_seconds": self.freshness_seconds,
            "sample_size": self.sample_size,
            "reliability_tier": self.reliability_tier.value,
            "metrics": dict(self.metrics),
            "unavailable_reason": self.unavailable_reason,
        }


def unavailable(
    spec: ModelSpec,
    symbol: str,
    reason: str,
    *,
    timeframes: tuple[str, ...] | None = None,
) -> ModelEvidence:
    """Explicit no-data result. Never fabricates a direction."""
    return ModelEvidence(
        model_id=spec.model_id,
        model_version=spec.version,
        family=spec.family,
        symbol=symbol,
        timeframes=timeframes or spec.timeframes,
        direction=EvidenceDirection.UNAVAILABLE,
        direction_score=0.0,
        confidence=0.0,
        theory=spec.description,
        data_quality=EvidenceQuality.UNAVAILABLE,
        unavailable_reason=reason,
    )


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def direction_from_score(score: float, threshold: float = 0.15) -> EvidenceDirection:
    if score > threshold:
        return EvidenceDirection.LONG
    if score < -threshold:
        return EvidenceDirection.SHORT
    return EvidenceDirection.NEUTRAL
