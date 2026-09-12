"""Regime adaptive weighting."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


class RegimeWeightEngine:
    BASE_WEIGHTS = {
        "trend": D("0.40"),
        "momentum": D("0.20"),
        "breakout": D("0.15"),
        "mean_reversion": D("0.10"),
        "funding_basis": D("0.15"),
    }

    def weights_for(self, regime: str) -> dict[str, Decimal]:
        weights = dict(self.BASE_WEIGHTS)
        if regime == "BULL":
            weights["trend"] += D("0.10")
            weights["mean_reversion"] -= D("0.05")
        elif regime == "BEAR":
            weights["trend"] += D("0.10")
            weights["mean_reversion"] += D("0.05")
        elif regime == "HIGH_VOL":
            weights["breakout"] += D("0.10")
            weights["momentum"] -= D("0.05")
        elif regime == "RANGE":
            weights["mean_reversion"] += D("0.10")
            weights["trend"] -= D("0.10")
        total = sum((w for w in weights.values() if w > 0), D("0"))
        if total <= 0:
            return dict(self.BASE_WEIGHTS)
        return {k: (v / total if v > 0 else D("0")) for k, v in weights.items()}
