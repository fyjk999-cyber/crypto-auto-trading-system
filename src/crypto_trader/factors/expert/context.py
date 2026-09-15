"""Inputs and all-in cost model for the 25-model expert evidence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from crypto_trader.market_data.opportunity.factors import Candle
from crypto_trader.market_data.state import MarketState

TIMEFRAMES: tuple[str, ...] = ("4h", "1h", "15m", "5m", "1m")
RESAMPLE_MINUTES: dict[str, int] = {"4h": 240, "1h": 60, "15m": 15, "5m": 5, "1m": 1}


@dataclass(slots=True)
class AllInCostEstimate:
    """Unified all-in economics estimate (engineering defaults until Growth validates)."""

    entry_fee_bps: float = 5.0
    exit_fee_bps: float = 5.0
    spread_bps: float = 1.0
    slippage_bps: float = 2.0
    funding_bps: float = 1.0
    safety_margin_bps: float = 3.0

    @property
    def total_cost_bps(self) -> float:
        return (
            self.entry_fee_bps
            + self.exit_fee_bps
            + self.spread_bps
            + self.slippage_bps
            + self.funding_bps
            + self.safety_margin_bps
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "entry_fee_bps": self.entry_fee_bps,
            "exit_fee_bps": self.exit_fee_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "funding_bps": self.funding_bps,
            "safety_margin_bps": self.safety_margin_bps,
            "total_cost_bps": self.total_cost_bps,
        }


@dataclass(slots=True)
class ExpertInputs:
    """One factual evaluation input bundle for a single symbol."""

    symbol: str
    candles: dict[str, list[Candle]] = field(default_factory=dict)
    state: MarketState | None = None
    costs: AllInCostEstimate = field(default_factory=AllInCostEstimate)
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def series(self, timeframe: str) -> list[Candle]:
        return self.candles.get(timeframe, [])

    @property
    def freshness_seconds(self) -> float | None:
        if self.state is None or self.state.received_timestamp is None:
            return None
        return max(0.0, (self.observed_at - self.state.received_timestamp).total_seconds())


def resample_candles(candles: list[Candle], factor_minutes: int) -> list[Candle]:
    """Deterministically aggregate closed 1m candles into a higher timeframe.

    Buckets are aligned to epoch multiples so the result is reproducible.
    """
    if factor_minutes <= 1 or not candles:
        return list(candles)
    bucket_ms = factor_minutes * 60_000
    buckets: dict[int, list[Candle]] = {}
    for candle in sorted(candles, key=lambda item: item.ts_ms):
        bucket = candle.ts_ms // bucket_ms
        buckets.setdefault(bucket, []).append(candle)
    out: list[Candle] = []
    for bucket in sorted(buckets):
        group = buckets[bucket]
        out.append(
            Candle(
                ts_ms=bucket * bucket_ms,
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(item.volume for item in group),
            )
        )
    return out


def build_timeframes(candles_1m: list[Candle]) -> dict[str, list[Candle]]:
    return {
        timeframe: resample_candles(candles_1m, RESAMPLE_MINUTES[timeframe])
        for timeframe in TIMEFRAMES
    }


def closes(candles: list[Candle]) -> list[float]:
    return [item.close for item in candles]


def highs(candles: list[Candle]) -> list[float]:
    return [item.high for item in candles]


def lows(candles: list[Candle]) -> list[float]:
    return [item.low for item in candles]


def volumes(candles: list[Candle]) -> list[float]:
    return [item.volume for item in candles]
