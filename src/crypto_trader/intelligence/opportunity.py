"""Opportunity ranking engine: LONG and SHORT candidates, no orders."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.domain.money import D
from crypto_trader.features.vectors import MarketFeatureVector
from crypto_trader.intelligence.derivatives import DerivativesSnapshot


@dataclass
class OpportunityCandidate:
    symbol: str
    side: str
    score: int
    state: str
    reasons: list[str]


class OpportunityEngine:
    def rank(
        self, features: list[MarketFeatureVector], derivatives: dict[str, DerivativesSnapshot]
    ) -> list[OpportunityCandidate]:
        candidates: list[OpportunityCandidate] = []
        for feature in features:
            score = D("50")
            reasons: list[str] = []
            if feature.price > 0 and feature.sma20 > 0:
                if feature.price > feature.sma20:
                    score += D("10")
                    reasons.append("PRICE_ABOVE_SMA")
                else:
                    score -= D("10")
                    reasons.append("PRICE_BELOW_SMA")
            if feature.roc5 > 0:
                score += D("8")
                reasons.append("MOMENTUM_POS")
            else:
                score -= D("8")
                reasons.append("MOMENTUM_NEG")
            if feature.volume_anomaly > D("1.5"):
                score += D("7")
                reasons.append("VOLUME_ANOMALY")
            if feature.realized_vol > D("3"):
                score -= D("5")
                reasons.append("HIGH_VOL")
            deriv = derivatives.get(feature.symbol)
            if deriv is not None:
                if deriv.funding_rate is not None and deriv.funding_rate < D("0.0001"):
                    score += D("5")
                    reasons.append("FUNDING_COOL")
                if deriv.oi_change_pct is not None and deriv.oi_change_pct > D("5"):
                    score += D("5")
                    reasons.append("OI_BUILD")
            side = "LONG" if score >= D("55") else "SHORT" if score <= D("45") else "WATCH"
            candidates.append(
                OpportunityCandidate(
                    symbol=feature.symbol,
                    side=side,
                    score=int(max(D("0"), min(D("100"), score))),
                    state="CONFIRMED" if side in ("LONG", "SHORT") else "WATCHING",
                    reasons=reasons,
                )
            )
        return sorted(candidates, key=lambda c: c.score, reverse=True)
