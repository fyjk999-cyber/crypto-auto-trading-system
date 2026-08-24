from decimal import Decimal

from crypto_trader.alpha.sub_strategy.base import (
    AlphaContext,
    AlphaSide,
    AlphaSignal,
    AlphaSubStrategy,
)
from crypto_trader.domain.money import D


class MeanReversionStrategy(AlphaSubStrategy):
    name = "mean_reversion"
    version = "0.1.0"

    def __init__(self, entry_z: str = "1.5") -> None:
        self.entry_z = D(entry_z)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        z = f.zscore_20
        if z < -self.entry_z:
            side, confidence, reasons = (
                AlphaSide.LONG,
                min(D("0.8"), D("0.45") + (-z) * D("0.2")),
                ["OVERSOLD"],
            )
        elif z > self.entry_z:
            side, confidence, reasons = (
                AlphaSide.SHORT,
                min(D("0.8"), D("0.45") + z * D("0.2")),
                ["OVERBOUGHT"],
            )
        else:
            side, confidence, reasons = AlphaSide.NO_TRADE, Decimal("0"), ["Z_WITHIN_BAND"]
        return self._signal(ctx, side, confidence, reasons, {"zscore": str(z)})
