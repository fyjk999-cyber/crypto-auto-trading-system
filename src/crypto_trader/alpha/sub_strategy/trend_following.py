from decimal import Decimal

from crypto_trader.alpha.sub_strategy.base import (
    AlphaContext,
    AlphaSide,
    AlphaSignal,
    AlphaSubStrategy,
)
from crypto_trader.domain.money import D


class TrendFollowingStrategy(AlphaSubStrategy):
    name = "trend_following"
    version = "0.1.0"

    def __init__(self, threshold: str = "0.002") -> None:
        self.threshold = D(threshold)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        trend = (f.ema_20 - f.ema_50) / f.ema_50 if f.ema_50 > 0 else Decimal("0")
        if trend > self.threshold:
            side, confidence, reasons = (
                AlphaSide.LONG,
                min(D("0.9"), D("0.5") + trend * 100),
                ["EMA_BULL"],
            )
        elif trend < -self.threshold:
            side, confidence, reasons = (
                AlphaSide.SHORT,
                min(D("0.9"), D("0.5") + (-trend) * 100),
                ["EMA_BEAR"],
            )
        else:
            side, confidence, reasons = AlphaSide.NO_TRADE, Decimal("0"), ["EMA_FLAT"]
        return self._signal(ctx, side, confidence, reasons, {"trend": str(trend)})
