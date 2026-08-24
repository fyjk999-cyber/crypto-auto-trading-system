from decimal import Decimal

from crypto_trader.alpha.sub_strategy.base import (
    AlphaContext,
    AlphaSide,
    AlphaSignal,
    AlphaSubStrategy,
)
from crypto_trader.domain.money import D


class MomentumStrategy(AlphaSubStrategy):
    name = "momentum"
    version = "0.1.0"

    def __init__(self, threshold: str = "0.004") -> None:
        self.threshold = D(threshold)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        mom = f.return_5
        if mom > self.threshold:
            side, confidence, reasons = (
                AlphaSide.LONG,
                min(D("0.85"), D("0.5") + mom * 40),
                ["MOMENTUM_POS"],
            )
        elif mom < -self.threshold:
            side, confidence, reasons = (
                AlphaSide.SHORT,
                min(D("0.85"), D("0.5") + (-mom) * 40),
                ["MOMENTUM_NEG"],
            )
        else:
            side, confidence, reasons = AlphaSide.NO_TRADE, Decimal("0"), ["MOMENTUM_FLAT"]
        return self._signal(ctx, side, confidence, reasons, {"momentum_5": str(mom)})
