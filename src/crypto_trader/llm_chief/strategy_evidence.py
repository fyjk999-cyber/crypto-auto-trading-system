"""Strategy-fit evidence for the Live Trading Brain.

Philosophy: the Live brain does not require all factors or all strategies to
agree. Each canonical strategy independently produces a candidate with a
direction and a REGIME-ADJUSTED fit score. The Live LLM selects the dominant
strategy and weighs supporting/contradicting evidence. Contradictions reduce
confidence; they are NOT automatic vetoes.

The default candidate pool contains the five canonical alpha strategies plus
five live crypto playbooks: trend pullback, breakout retest, liquidity sweep,
support/resistance reversal, and market structure. Existing alpha ensemble
weights remain priors for the legacy alpha stack only; StrategyEvidenceBuilder
ranks every candidate independently and never averages them into one entry gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.alpha.features import FeatureSnapshot, compute_features
from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.alpha.regime import MarketRegime, RegimeEngine
from crypto_trader.alpha.sub_strategy import (
    BreakoutRetestStrategy,
    BreakoutStrategy,
    FundingBasisStrategy,
    LiquiditySweepStrategy,
    MarketStructureStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    SupportResistanceReversalStrategy,
    TrendFollowingStrategy,
    TrendPullbackStrategy,
)
from crypto_trader.alpha.sub_strategy.base import AlphaContext, AlphaSignal

# Legacy priors from MultiStrategyAlpha. They are retained as documentation for
# the canonical alpha stack and are not used as a weighted-average trade gate.
BASE_PRIORS: dict[str, float] = {
    "trend_following": 0.40,
    "momentum": 0.20,
    "breakout": 0.15,
    "mean_reversion": 0.10,
    "funding_basis": 0.15,
}

# Regime changes the fit of each candidate; it never hard-mandates a strategy.
REGIME_FIT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "BULL": {
        "trend_following": 1.25,
        "momentum": 1.10,
        "breakout": 0.90,
        "mean_reversion": 0.70,
        "funding_basis": 0.90,
        "trend_pullback": 1.25,
        "breakout_retest": 1.05,
        "liquidity_sweep": 0.85,
        "support_resistance_reversal": 0.75,
        "market_structure": 1.20,
    },
    "BEAR": {
        "trend_following": 1.20,
        "momentum": 1.00,
        "breakout": 0.90,
        "mean_reversion": 0.80,
        "funding_basis": 1.00,
        "trend_pullback": 1.25,
        "breakout_retest": 1.05,
        "liquidity_sweep": 0.90,
        "support_resistance_reversal": 0.80,
        "market_structure": 1.20,
    },
    "RANGE": {
        "trend_following": 0.60,
        "momentum": 0.80,
        "breakout": 0.70,
        "mean_reversion": 1.40,
        "funding_basis": 1.00,
        "trend_pullback": 0.65,
        "breakout_retest": 0.75,
        "liquidity_sweep": 1.25,
        "support_resistance_reversal": 1.35,
        "market_structure": 0.70,
    },
    "HIGH_VOL": {
        "trend_following": 0.80,
        "momentum": 0.90,
        "breakout": 1.30,
        "mean_reversion": 1.00,
        "funding_basis": 1.00,
        "trend_pullback": 0.75,
        "breakout_retest": 1.15,
        "liquidity_sweep": 1.25,
        "support_resistance_reversal": 1.05,
        "market_structure": 0.85,
    },
    "EXTREME_RISK": {
        "trend_following": 0.70,
        "momentum": 0.80,
        "breakout": 1.10,
        "mean_reversion": 0.90,
        "funding_basis": 1.10,
        "trend_pullback": 0.65,
        "breakout_retest": 0.85,
        "liquidity_sweep": 0.90,
        "support_resistance_reversal": 0.80,
        "market_structure": 0.65,
    },
}

# Funding/basis dislocation (independent of candle regime) boosts FundingBasis.
FUNDING_DISLOCATION_THRESHOLD = Decimal("0.0005")
FUNDING_DISLOCATION_MULTIPLIER = 1.50


class StrategyCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    strategy_version: str
    direction: str  # LONG | SHORT | NO_TRADE
    fit_score: float
    raw_confidence: float
    supporting_factors: list[str] = Field(default_factory=list)
    contradicting_factors: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    data_health: str = "OK"


class StrategyEvidencePackage(BaseModel):
    """Canonical per-tick strategy evidence handed to CryptoTrader-Live."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    timestamp: str
    market_regime: str
    regime_detail: dict = Field(default_factory=dict)
    strategy_candidates: list[StrategyCandidate] = Field(default_factory=list)
    dominant_factors: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    market_quality: dict = Field(default_factory=dict)

    def directional(self) -> list[StrategyCandidate]:
        return [c for c in self.strategy_candidates if c.direction in ("LONG", "SHORT")]

    def best_candidate(self) -> StrategyCandidate | None:
        directional = self.directional()
        if not directional:
            return None
        return max(directional, key=lambda c: c.fit_score)


def _f(d: Decimal | float | None) -> float:
    return float(d) if d is not None else 0.0


def _fit(
    confidence: Decimal,
    strategy_id: str,
    regime: str,
    funding_dislocation: bool,
) -> float:
    mult = REGIME_FIT_MULTIPLIERS.get(regime, {}).get(strategy_id, 1.0)
    if funding_dislocation and strategy_id == "funding_basis":
        mult *= FUNDING_DISLOCATION_MULTIPLIER
    return round(min(1.0, _f(confidence) * mult), 4)


def _zscore_extreme(feature: FeatureSnapshot) -> bool:
    return abs(_f(feature.zscore_20)) > 2.0


def _funding_crowded(feature: FeatureSnapshot) -> bool:
    return feature.funding_available and abs(_f(feature.funding)) > _f(
        FUNDING_DISLOCATION_THRESHOLD
    )


def _attribute(strategy_id: str, feature: FeatureSnapshot) -> tuple[list[str], list[str]]:
    """Deterministic factor attribution from existing feature truth only."""
    supporting: list[str] = []
    contradicting: list[str] = []
    up = _f(feature.ema_20) > _f(feature.ema_50)
    rising_volume = _f(feature.volume_ratio_20) > 1.0
    funding_crowded = _funding_crowded(feature)
    z_extreme = _zscore_extreme(feature)
    vol_high = _f(feature.realized_vol_20) > 0.02

    if strategy_id == "trend_following":
        supporting += ["trend"]
        if (_f(feature.return_20) > 0) == up and _f(feature.return_20) != 0:
            supporting.append("momentum")
        if rising_volume:
            supporting.append("volume_change")
        if funding_crowded:
            contradicting.append("funding_rate")
        if z_extreme:
            contradicting.append("mean_reversion")
    elif strategy_id == "momentum":
        supporting += ["momentum", "return"]
        if rising_volume:
            supporting.append("volume_change")
        if z_extreme:
            contradicting.append("mean_reversion")
    elif strategy_id == "breakout":
        high = _f(feature.donchian_high_50)
        if high > 0 and _f(feature.price) >= high * 0.99:
            supporting += ["breakout", "trend"]
        if _f(feature.volume_ratio_20) > 1.5:
            supporting.append("volume_change")
        if vol_high:
            supporting.append("volatility_regime")
            contradicting.append("realized_volatility")
    elif strategy_id == "mean_reversion":
        if z_extreme:
            supporting += ["mean_reversion"]
        if funding_crowded:
            supporting.append("funding_rate")
        if (
            abs(_f(feature.ema_20) - _f(feature.ema_50))
            / max(_f(feature.ema_50), 1e-9)
            > 0.002
        ):
            contradicting.append("trend")
    elif strategy_id == "funding_basis":
        if feature.funding_available:
            supporting += ["funding_rate", "funding_change"]
        if feature.oi_available:
            supporting.append("open_interest")
        if up:
            contradicting.append("trend")
    elif strategy_id == "trend_pullback":
        supporting += ["trend", "mean_reversion"]
        if _f(feature.return_20) != 0:
            supporting.append("return")
        if z_extreme:
            contradicting.append("mean_reversion")
        if funding_crowded:
            contradicting.append("funding_rate")
    elif strategy_id == "breakout_retest":
        supporting += ["breakout", "trend"]
        if rising_volume:
            supporting.append("volume_change")
        if z_extreme:
            contradicting.append("mean_reversion")
        if vol_high:
            contradicting.append("realized_volatility")
    elif strategy_id == "liquidity_sweep":
        supporting += ["mean_reversion", "return"]
        if rising_volume:
            supporting.append("volume_change")
        if vol_high:
            supporting.append("volatility_regime")
        if abs(_f(feature.return_20)) > 0.03:
            contradicting.append("trend")
    elif strategy_id == "support_resistance_reversal":
        supporting += ["mean_reversion", "return"]
        if rising_volume:
            supporting.append("volume_change")
        if abs(_f(feature.return_20)) > 0.03:
            contradicting.append("trend")
    elif strategy_id == "market_structure":
        supporting += ["trend", "momentum", "return"]
        if rising_volume:
            supporting.append("volume_change")
        if z_extreme:
            contradicting.append("mean_reversion")
        if funding_crowded:
            contradicting.append("funding_rate")
    return supporting, contradicting


def _data_health(strategy_id: str, feature: FeatureSnapshot) -> str:
    if strategy_id == "funding_basis" and (
        not feature.funding_available or not feature.basis_available
    ):
        return "DERIVATIVES_DATA_UNAVAILABLE"
    if strategy_id == "liquidity_sweep":
        return "PROXY_NO_WICK_OR_ORDERFLOW"
    if strategy_id == "breakout_retest":
        return "PROXY_CLOSE_BASED_RETEST"
    if strategy_id == "market_structure":
        return "PROXY_EMA_RETURN_STRUCTURE"
    return "OK"


class StrategyEvidenceBuilder:
    """Deterministic ten-strategy evidence builder for the PAPER decision layer."""

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        regime_engine: RegimeEngine | None = None,
        strategies: list | None = None,
    ) -> None:
        self.symbol = symbol
        self.mde = MarketDataEngine(symbol)
        self.regime_engine = regime_engine or RegimeEngine()
        self.strategies = strategies or [
            TrendFollowingStrategy(),
            MomentumStrategy(),
            BreakoutStrategy(),
            MeanReversionStrategy(),
            FundingBasisStrategy(),
            TrendPullbackStrategy(),
            BreakoutRetestStrategy(),
            LiquiditySweepStrategy(),
            SupportResistanceReversalStrategy(),
            MarketStructureStrategy(),
        ]

    def build(
        self,
        candles: list[dict],
        market_data: dict | None,
        timestamp: str | None = None,
    ) -> StrategyEvidencePackage:
        """Build strategy evidence from oldest-first closed candles.

        Uses a fresh MarketDataEngine per call because candle windows overlap
        between consecutive builds and ingest() requires monotonic timestamps.
        RegimeEngine state (volatility percentiles) persists.
        """
        md = market_data or {}
        from decimal import Decimal as D

        self.mde = MarketDataEngine(self.symbol)
        now = timestamp or datetime.now(UTC).isoformat()
        candle_count = 0
        for candle in candles:
            try:
                ts = datetime.fromisoformat(str(candle["open_time"]))
                mid = D(str(candle.get("close", "0")))
                if mid <= 0:
                    continue
                volume = max(D(str(candle.get("volume", "0"))), D("0.0001"))
                self.mde.ingest(
                    ts,
                    mid,
                    volume,
                    oi=md.get("open_interest"),
                    funding=md.get("funding_rate"),
                    basis=md.get("basis"),
                )
                candle_count += 1
            except (KeyError, ValueError, TypeError):
                continue
        if candle_count < 30:
            return StrategyEvidencePackage(
                symbol=self.symbol,
                timestamp=now,
                market_regime="UNKNOWN",
                regime_detail={"reason": "INSUFFICIENT_HISTORY"},
                risk_flags=["INSUFFICIENT_HISTORY"],
                market_quality={
                    "candle_count": candle_count,
                    "price_ok": candle_count > 0,
                    "funding_available": False,
                    "oi_available": False,
                    "basis_available": False,
                },
            )
        feature = compute_features(self.mde, self.symbol, self.mde.latest().ts)
        regime = self.regime_engine.classify(feature)
        regime_name = regime.regime.value
        alpha_ctx = AlphaContext(
            symbol=self.symbol,
            ts=feature.ts,
            feature=feature,
            regime=regime,
        )
        funding_dislocation = feature.funding_available and feature.basis_available and (
            abs(_f(feature.funding) + _f(feature.basis))
            > _f(FUNDING_DISLOCATION_THRESHOLD)
        )
        candidates: list[StrategyCandidate] = []
        for strategy in self.strategies:
            signal: AlphaSignal = strategy.evaluate(alpha_ctx)
            supporting, contradicting = _attribute(strategy.name, feature)
            candidates.append(
                StrategyCandidate(
                    strategy_id=strategy.name,
                    strategy_version=strategy.version,
                    direction=signal.side.value,
                    fit_score=_fit(
                        signal.confidence,
                        strategy.name,
                        regime_name,
                        funding_dislocation,
                    ),
                    raw_confidence=_f(signal.confidence),
                    supporting_factors=supporting,
                    contradicting_factors=contradicting,
                    reason_codes=list(signal.reason_codes),
                    data_health=_data_health(strategy.name, feature),
                )
            )
        risk_flags: list[str] = []
        if funding_dislocation and _f(feature.funding) > 0:
            risk_flags.append("FUNDING_CROWDED_LONGS")
        if funding_dislocation and _f(feature.funding) < 0:
            risk_flags.append("FUNDING_CROWDED_SHORTS")
        if regime.regime == MarketRegime.EXTREME_RISK:
            risk_flags.append("EXTREME_VOLATILITY")
        best = max(candidates, key=lambda c: c.fit_score)
        dominant_factors = list(dict.fromkeys(best.supporting_factors))[:3]
        return StrategyEvidencePackage(
            symbol=self.symbol,
            timestamp=now,
            market_regime=regime_name,
            regime_detail={
                "trend_score": regime.trend_score,
                "vol_score": regime.vol_score,
                "reason_codes": list(regime.reason_codes),
            },
            strategy_candidates=candidates,
            dominant_factors=dominant_factors,
            risk_flags=risk_flags,
            market_quality={
                "candle_count": candle_count,
                "price_ok": True,
                "funding_available": feature.funding_available,
                "oi_available": feature.oi_available,
                "basis_available": feature.basis_available,
            },
        )
