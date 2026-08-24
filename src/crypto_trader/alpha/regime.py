"""Market regime engine: BULL/BEAR/RANGE/HIGH_VOL/EXTREME_RISK."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.alpha.features import FeatureSnapshot
from crypto_trader.domain.money import D


class MarketRegime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"
    EXTREME_RISK = "EXTREME_RISK"


class RegimeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    ts: datetime
    version: int
    regime: MarketRegime
    reason_codes: list[str] = Field(default_factory=list)
    trend_score: float | None = None
    vol_score: float | None = None


class RegimeEngine:
    def __init__(
        self, high_vol_percentile: float = 0.80, extreme_vol_percentile: float = 0.95
    ) -> None:
        self.high_vol_percentile = D(str(high_vol_percentile))
        self.extreme_vol_percentile = D(str(extreme_vol_percentile))
        self._vol_hist: list[tuple[str, object]] = []  # (symbol, Decimal)
        self._version = 0

    def classify(
        self, feature: FeatureSnapshot, *, vol_percentile: float | None = None
    ) -> RegimeOutput:
        self._version += 1
        trend_score = float(
            (feature.ema_20 - feature.ema_50) / feature.ema_50 if feature.ema_50 > 0 else 0.0
        )
        vol = feature.realized_vol_20
        vol_score = float(vol)
        self._vol_hist.append((feature.symbol, vol))
        reasons: list[str] = []

        if vol_percentile is not None:
            pct = D(str(vol_percentile))
        elif len([1 for sym, _ in self._vol_hist if sym == feature.symbol]) < 10:
            pct = D("0.5")
        else:
            pct = self.percentile_for(feature.symbol, vol)

        if pct >= self.extreme_vol_percentile:
            regime = MarketRegime.EXTREME_RISK
            reasons.append("EXTREME_VOL")
        elif pct >= self.high_vol_percentile:
            regime = MarketRegime.HIGH_VOL
            reasons.append("HIGH_VOL")
        elif trend_score > 0.01:
            regime = MarketRegime.BULL
            reasons.append("TREND_UP")
        elif trend_score < -0.01:
            regime = MarketRegime.BEAR
            reasons.append("TREND_DOWN")
        else:
            regime = MarketRegime.RANGE
            reasons.append("RANGE_BOUND")
        return RegimeOutput(
            symbol=feature.symbol,
            ts=feature.ts,
            version=self._version,
            regime=regime,
            reason_codes=reasons,
            trend_score=trend_score,
            vol_score=vol_score,
        )

    def percentile_for(self, symbol: str, vol: object) -> float:
        values = sorted((v for s, v in self._vol_hist if s == symbol), key=lambda x: float(x))
        if not values:
            return 0.5
        return float(sum(1 for v in values if v <= vol) / len(values))

    def record_vol(self, symbol: str, vol: object) -> None:
        self._vol_hist.append((symbol, vol))
