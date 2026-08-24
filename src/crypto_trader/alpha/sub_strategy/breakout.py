from decimal import Decimal

from crypto_trader.alpha.sub_strategy.base import (
    AlphaContext,
    AlphaSide,
    AlphaSignal,
    AlphaSubStrategy,
)
from crypto_trader.domain.money import D


class BreakoutStrategy(AlphaSubStrategy):
    name = "breakout"
    version = "0.1.0"

    def __init__(self, buffer: str = "0.0002") -> None:
        self.buffer = D(buffer)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        if f.donchian_high_50 > 0 and f.price > f.donchian_high_50 * (D("1") + self.buffer):
            side, confidence, reasons = AlphaSide.LONG, D("0.8"), ["BREAKOUT_UP"]
        elif f.donchian_low_50 > 0 and f.price < f.donchian_low_50 * (D("1") - self.buffer):
            side, confidence, reasons = AlphaSide.SHORT, D("0.8"), ["BREAKOUT_DOWN"]
        else:
            side, confidence, reasons = AlphaSide.NO_TRADE, Decimal("0"), ["NO_BREAKOUT"]
        return self._signal(ctx, side, confidence, reasons, {"range": str(f.price)})
