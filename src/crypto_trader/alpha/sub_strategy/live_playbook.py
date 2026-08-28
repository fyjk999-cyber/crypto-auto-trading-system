"""Live crypto trading playbooks expressed through the canonical AlphaSubStrategy contract.

These strategies intentionally use only features that already exist in FeatureSnapshot.
Where the full setup would normally require wick/order-flow data, the strategy fails
closed unless a conservative close/volume proxy is present and emits an explicit
reason code so the Chief Trader can discount the evidence.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.alpha.sub_strategy.base import (
    AlphaContext,
    AlphaSide,
    AlphaSignal,
    AlphaSubStrategy,
)
from crypto_trader.domain.money import D


def _trend_pct(ctx: AlphaContext) -> Decimal:
    f = ctx.feature
    if f.ema_50 <= 0:
        return Decimal("0")
    return (f.ema_20 - f.ema_50) / f.ema_50


def _near(price: Decimal, level: Decimal, tolerance: Decimal) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance


class TrendPullbackStrategy(AlphaSubStrategy):
    """Trade a controlled pullback while the higher-timeframe trend remains intact."""

    name = "trend_pullback"
    version = "0.1.0"

    def __init__(self, trend_threshold: str = "0.004", pullback_zone: str = "0.006") -> None:
        self.trend_threshold = D(trend_threshold)
        self.pullback_zone = D(pullback_zone)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        trend = _trend_pct(ctx)
        long_pullback = (
            trend > self.trend_threshold
            and f.return_20 > 0
            and f.price >= f.ema_50
            and f.price <= f.ema_20 * (D("1") + self.pullback_zone)
            and f.zscore_20 <= D("0.75")
        )
        short_pullback = (
            trend < -self.trend_threshold
            and f.return_20 < 0
            and f.price <= f.ema_50
            and f.price >= f.ema_20 * (D("1") - self.pullback_zone)
            and f.zscore_20 >= D("-0.75")
        )
        if long_pullback:
            confidence = min(D("0.88"), D("0.55") + abs(trend) * 35)
            reasons = ["TREND_UP_INTACT", "PULLBACK_TO_VALUE_ZONE"]
            side = AlphaSide.LONG
        elif short_pullback:
            confidence = min(D("0.88"), D("0.55") + abs(trend) * 35)
            reasons = ["TREND_DOWN_INTACT", "PULLBACK_TO_VALUE_ZONE"]
            side = AlphaSide.SHORT
        else:
            confidence = Decimal("0")
            reasons = ["NO_VALID_TREND_PULLBACK"]
            side = AlphaSide.NO_TRADE
        return self._signal(
            ctx,
            side,
            confidence,
            reasons,
            {"trend_pct": str(trend), "zscore_20": str(f.zscore_20)},
        )


class BreakoutRetestStrategy(AlphaSubStrategy):
    """Breakout/retest proxy using prior Donchian boundary, trend and reclaim momentum."""

    name = "breakout_retest"
    version = "0.1.0"

    def __init__(self, retest_tolerance: str = "0.006") -> None:
        self.retest_tolerance = D(retest_tolerance)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        near_high = _near(f.price, f.donchian_high_50, self.retest_tolerance)
        near_low = _near(f.price, f.donchian_low_50, self.retest_tolerance)
        long_setup = (
            near_high
            and f.return_20 > 0
            and f.return_1 > 0
            and f.volume_ratio_20 >= D("0.8")
            and f.zscore_20 < D("2.5")
        )
        short_setup = (
            near_low
            and f.return_20 < 0
            and f.return_1 < 0
            and f.volume_ratio_20 >= D("0.8")
            and f.zscore_20 > D("-2.5")
        )
        if long_setup:
            confidence = min(D("0.86"), D("0.54") + min(f.volume_ratio_20, D("2")) * D("0.08"))
            reasons = ["PRIOR_HIGH_RETEST_PROXY", "RECLAIM_MOMENTUM_UP"]
            side = AlphaSide.LONG
        elif short_setup:
            confidence = min(D("0.86"), D("0.54") + min(f.volume_ratio_20, D("2")) * D("0.08"))
            reasons = ["PRIOR_LOW_RETEST_PROXY", "RECLAIM_MOMENTUM_DOWN"]
            side = AlphaSide.SHORT
        else:
            confidence = Decimal("0")
            reasons = ["NO_VALID_BREAKOUT_RETEST"]
            side = AlphaSide.NO_TRADE
        return self._signal(
            ctx,
            side,
            confidence,
            reasons,
            {
                "donchian_high_50": str(f.donchian_high_50),
                "donchian_low_50": str(f.donchian_low_50),
                "proxy": "close_based_retest",
            },
        )


class LiquiditySweepStrategy(AlphaSubStrategy):
    """Conservative sweep/reclaim proxy; full wick/order-flow confirmation is unavailable."""

    name = "liquidity_sweep"
    version = "0.1.0"

    def __init__(self, boundary_tolerance: str = "0.004") -> None:
        self.boundary_tolerance = D(boundary_tolerance)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        near_low = _near(f.price, f.donchian_low_50, self.boundary_tolerance)
        near_high = _near(f.price, f.donchian_high_50, self.boundary_tolerance)
        long_setup = (
            near_low
            and f.zscore_20 <= D("-1.5")
            and f.return_1 > 0
            and f.volume_ratio_20 >= D("1.2")
        )
        short_setup = (
            near_high
            and f.zscore_20 >= D("1.5")
            and f.return_1 < 0
            and f.volume_ratio_20 >= D("1.2")
        )
        if long_setup:
            confidence = min(D("0.80"), D("0.50") + min(abs(f.zscore_20), D("3")) * D("0.08"))
            reasons = ["LOW_BOUNDARY_SWEEP_PROXY", "CLOSE_RECLAIM_UP", "SWEEP_PROXY_CLOSE_ONLY"]
            side = AlphaSide.LONG
        elif short_setup:
            confidence = min(D("0.80"), D("0.50") + min(abs(f.zscore_20), D("3")) * D("0.08"))
            reasons = ["HIGH_BOUNDARY_SWEEP_PROXY", "CLOSE_RECLAIM_DOWN", "SWEEP_PROXY_CLOSE_ONLY"]
            side = AlphaSide.SHORT
        else:
            confidence = Decimal("0")
            reasons = ["NO_VALID_LIQUIDITY_SWEEP", "SWEEP_PROXY_CLOSE_ONLY"]
            side = AlphaSide.NO_TRADE
        return self._signal(
            ctx,
            side,
            confidence,
            reasons,
            {"proxy": "no_wick_or_orderflow_data"},
        )


class SupportResistanceReversalStrategy(AlphaSubStrategy):
    """Fade a tested Donchian support/resistance boundary after directional rejection."""

    name = "support_resistance_reversal"
    version = "0.1.0"

    def __init__(self, level_tolerance: str = "0.006") -> None:
        self.level_tolerance = D(level_tolerance)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        near_low = _near(f.price, f.donchian_low_50, self.level_tolerance)
        near_high = _near(f.price, f.donchian_high_50, self.level_tolerance)
        long_setup = near_low and f.zscore_20 <= D("-0.75") and f.return_1 > 0
        short_setup = near_high and f.zscore_20 >= D("0.75") and f.return_1 < 0
        if long_setup:
            confidence = min(D("0.82"), D("0.52") + min(abs(f.zscore_20), D("2.5")) * D("0.08"))
            reasons = ["SUPPORT_ZONE_TEST", "REJECTION_UP"]
            side = AlphaSide.LONG
        elif short_setup:
            confidence = min(D("0.82"), D("0.52") + min(abs(f.zscore_20), D("2.5")) * D("0.08"))
            reasons = ["RESISTANCE_ZONE_TEST", "REJECTION_DOWN"]
            side = AlphaSide.SHORT
        else:
            confidence = Decimal("0")
            reasons = ["NO_VALID_SR_REVERSAL"]
            side = AlphaSide.NO_TRADE
        return self._signal(ctx, side, confidence, reasons)


class MarketStructureStrategy(AlphaSubStrategy):
    """Structure continuation proxy from EMA alignment plus multi-horizon returns."""

    name = "market_structure"
    version = "0.1.0"

    def __init__(self, structure_threshold: str = "0.003") -> None:
        self.structure_threshold = D(structure_threshold)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        trend = _trend_pct(ctx)
        long_setup = (
            trend > self.structure_threshold
            and f.return_5 > 0
            and f.return_20 > 0
            and f.price >= f.ema_20
            and f.zscore_20 < D("2.5")
        )
        short_setup = (
            trend < -self.structure_threshold
            and f.return_5 < 0
            and f.return_20 < 0
            and f.price <= f.ema_20
            and f.zscore_20 > D("-2.5")
        )
        if long_setup:
            confidence = min(D("0.90"), D("0.55") + abs(trend) * 35)
            reasons = ["BULL_STRUCTURE_PROXY", "MULTI_HORIZON_CONFIRMATION"]
            side = AlphaSide.LONG
        elif short_setup:
            confidence = min(D("0.90"), D("0.55") + abs(trend) * 35)
            reasons = ["BEAR_STRUCTURE_PROXY", "MULTI_HORIZON_CONFIRMATION"]
            side = AlphaSide.SHORT
        else:
            confidence = Decimal("0")
            reasons = ["NO_VALID_MARKET_STRUCTURE"]
            side = AlphaSide.NO_TRADE
        return self._signal(
            ctx,
            side,
            confidence,
            reasons,
            {"trend_pct": str(trend), "proxy": "ema_and_returns"},
        )
