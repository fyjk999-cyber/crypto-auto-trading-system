"""ML Meta layer.

Not a directional 5% alpha. It sits after the ensemble and:
- adjusts per-decision effective weights by Regime + Performance + simple ML score
- calibrates confidence
- builds the final MetaDecision.

Production base weights are never mutated here; only per-decision weights are
returned, so Fast Learning cannot silently modify production strategy.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from crypto_trader.alpha.learning import FastLearning
from crypto_trader.alpha.meta_decision import MetaDecision
from crypto_trader.alpha.regime import MarketRegime
from crypto_trader.alpha.sub_strategy.base import AlphaSide, AlphaSignal
from crypto_trader.domain.money import D

BASE_WEIGHTS: dict[str, Decimal] = {
    "trend_following": D("0.40"),
    "momentum": D("0.20"),
    "breakout": D("0.15"),
    "mean_reversion": D("0.10"),
    "funding_basis": D("0.15"),
}

REGIME_WEIGHT_ADJUST = {
    MarketRegime.BULL: {
        "trend_following": D("0.10"),
        "momentum": D("0.05"),
        "mean_reversion": D("-0.05"),
    },
    MarketRegime.BEAR: {
        "trend_following": D("0.10"),
        "momentum": D("-0.05"),
        "mean_reversion": D("-0.05"),
    },
    MarketRegime.RANGE: {
        "mean_reversion": D("0.10"),
        "breakout": D("0.05"),
        "trend_following": D("-0.10"),
    },
    MarketRegime.HIGH_VOL: {
        "breakout": D("0.05"),
        "mean_reversion": D("-0.10"),
        "funding_basis": D("0.05"),
    },
    MarketRegime.EXTREME_RISK: {
        "trend_following": D("-0.20"),
        "momentum": D("-0.10"),
        "breakout": D("-0.10"),
        "funding_basis": D("0.10"),
    },
}


class MLMeta:
    name = "ml_meta"
    version = "0.1.0"

    def __init__(self, fast_learning: FastLearning | None = None) -> None:
        self.fast_learning = fast_learning or FastLearning()

    def decide(
        self,
        *,
        symbol: str,
        ts: datetime,
        regime,
        signals: list[AlphaSignal],
        run_id: str | None = None,
    ) -> MetaDecision:
        eff_weights = self.effective_weights(regime.regime, signals)
        long_score = D("0")
        short_score = D("0")
        vote_scores: dict[str, Decimal] = {}
        reasons: list[str] = []

        for signal in signals:
            w = eff_weights.get(signal.strategy, D("0"))
            if w <= 0:
                continue
            if signal.side == AlphaSide.LONG:
                long_score += w * signal.confidence
            elif signal.side == AlphaSide.SHORT:
                short_score += w * signal.confidence
            vote_scores[signal.strategy] = w * signal.confidence
            reasons.extend(signal.reason_codes)

        total_weight = sum(eff_weights.values(), D("0"))
        if total_weight > 0:
            long_score = long_score / total_weight
            short_score = short_score / total_weight

        if long_score <= 0 and short_score <= 0:
            side = AlphaSide.NO_TRADE
            raw_confidence = D("0")
            reasons.append("NO_ALPHA")
        elif long_score >= short_score:
            side = AlphaSide.LONG
            raw_confidence = min(D("0.95"), long_score)
        else:
            side = AlphaSide.SHORT
            raw_confidence = min(D("0.95"), short_score)

        confidence = self.calibrate(side, raw_confidence, regime.regime, symbol)
        return MetaDecision(
            symbol=symbol,
            ts=ts,
            version=self.version,
            side=side,
            confidence=confidence,
            reason_codes=sorted(set(reasons)),
            effective_weights={k: v for k, v in sorted(eff_weights.items())},
            vote_scores={k: v for k, v in sorted(vote_scores.items())},
            regime=regime.regime.value,
            run_id=run_id,
        )

    def effective_weights(
        self, regime: MarketRegime, signals: list[AlphaSignal]
    ) -> dict[str, Decimal]:
        weights = dict(BASE_WEIGHTS)
        for strategy, delta in REGIME_WEIGHT_ADJUST.get(regime, {}).items():
            weights[strategy] = weights.get(strategy, D("0")) + delta
        # small performance prior from Fast Learning (clamped, per-decision only)
        for signal in signals:
            perf_score = self.fast_learning.strategy_score(signal.strategy)
            if perf_score is not None:
                weights[signal.strategy] = weights.get(signal.strategy, D("0")) + perf_score
        # normalize
        total = sum((w for w in weights.values() if w > 0), D("0"))
        if total > 0:
            return {k: (v / total if v > 0 else D("0")) for k, v in weights.items()}
        return dict(BASE_WEIGHTS)

    def calibrate(
        self, side: AlphaSide, raw: Decimal, regime: MarketRegime, symbol: str
    ) -> Decimal:
        if side == AlphaSide.NO_TRADE:
            return D("0")
        factor = D("1.0")
        if regime == MarketRegime.EXTREME_RISK:
            factor = D("0.55")
        elif regime == MarketRegime.HIGH_VOL:
            factor = D("0.80")
        elif regime == MarketRegime.RANGE:
            factor = D("0.90")
        calibrated = raw * factor
        # Fast Learning confidence calibration (symmetric, bounded)
        cal = self.fast_learning.confidence_calibration(symbol, side.value)
        calibrated = min(D("0.95"), max(D("0.05"), calibrated + cal))
        return calibrated
