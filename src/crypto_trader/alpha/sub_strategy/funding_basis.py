from decimal import Decimal

from crypto_trader.alpha.sub_strategy.base import (
    AlphaContext,
    AlphaSide,
    AlphaSignal,
    AlphaSubStrategy,
)
from crypto_trader.domain.money import D


class FundingBasisStrategy(AlphaSubStrategy):
    name = "funding_basis"
    version = "0.1.0"

    def __init__(self, funding_threshold: str = "0.0005") -> None:
        self.funding_threshold = D(funding_threshold)

    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        f = ctx.feature
        if not f.funding_available or not f.basis_available:
            reasons = []
            if not f.funding_available:
                reasons.append("FUNDING_DATA_UNAVAILABLE")
            if not f.basis_available:
                reasons.append("BASIS_DATA_UNAVAILABLE")
            return self._signal(ctx, AlphaSide.NO_TRADE, Decimal("0"), reasons)
        score = f.funding + f.basis
        if score < -self.funding_threshold:
            side, confidence, reasons = (
                AlphaSide.LONG,
                min(D("0.75"), D("0.4") + (-score) * 300),
                ["FUNDING_LONG_BIAS"],
            )
        elif score > self.funding_threshold:
            side, confidence, reasons = (
                AlphaSide.SHORT,
                min(D("0.75"), D("0.4") + score * 300),
                ["FUNDING_SHORT_BIAS"],
            )
        else:
            side, confidence, reasons = AlphaSide.NO_TRADE, Decimal("0"), ["FUNDING_NEUTRAL"]
        return self._signal(
            ctx, side, confidence, reasons, {"funding": str(f.funding), "basis": str(f.basis)}
        )
