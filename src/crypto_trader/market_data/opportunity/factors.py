"""Independent factor detectors (MASTER DIRECTIVE §6/§12/§27/§28).

Every detector is independent: it evaluates factual inputs and reports one
of three statuses:

    TRIGGERED      the factor's factual trigger condition is met
    NOT_TRIGGERED  evaluated fine, condition not met
    UNAVAILABLE    required factual input missing/insufficient

Outputs are FACTUAL observations (e.g. MOMENTUM_EXPANSION with measured
returns), never directional commands (no LONG/SHORT/BUY/SELL semantics).
Strength is a factual distance measure, not a trade permission.

Thresholds are stable configuration (§43): learning never mutates them.
A detector being UNAVAILABLE never blocks anything else (§28) — the scanner
merely records it and DeepSeek continues on other evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

TRIGGERED = "TRIGGERED"
NOT_TRIGGERED = "NOT_TRIGGERED"
UNAVAILABLE = "UNAVAILABLE"

DETECTOR_VERSION = "factors-v1"


@dataclass(frozen=True, slots=True)
class Candle:
    """One factual closed candle (ascending order externally)."""

    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class FactorThresholds:
    momentum_return_15m: float = 0.008
    momentum_return_5m: float = 0.004
    breakout_lookback: int = 20
    breakout_min_distance_bps: float = 1.0
    volume_ratio: float = 2.5
    volume_baseline_bars: int = 60
    volume_recent_bars: int = 5
    mean_reversion_zscore: float = 2.5
    mean_reversion_window: int = 30
    volatility_expansion_ratio: float = 2.0
    volatility_recent_bars: int = 15
    volatility_baseline_bars: int = 60
    funding_extreme: float = 0.0015
    oi_change_pct: float = 3.0
    orderbook_imbalance_ratio: float = 3.0
    liquidity_anomaly_ratio: float = 0.15


@dataclass(slots=True)
class SymbolFacts:
    """Bounded factual per-symbol market facts for one scan cycle."""

    symbol: str
    candles: list[Candle] = field(default_factory=list)  # ascending, closed
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_qty: float | None = None
    ask_qty: float | None = None
    volume_24h_usd: float | None = None
    price_change_24h_pct: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    oi_change_pct: float | None = None  # computed by scanner over rolling history
    oi_samples: int = 0
    cohort_median_turnover_usd: float | None = None
    observed_at: datetime | None = None


@dataclass(slots=True)
class FactorObservation:
    symbol: str
    factor: str
    status: str  # TRIGGERED | NOT_TRIGGERED | UNAVAILABLE
    strength: float | None = None
    facts: dict = field(default_factory=dict)
    observed_at: str = ""
    detector_version: str = DETECTOR_VERSION
    unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "factor": self.factor,
            "status": self.status,
            "strength": self.strength,
            "facts": self.facts,
            "observed_at": self.observed_at,
            "detector_version": self.detector_version,
            "unavailable_reason": self.unavailable_reason,
        }


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _strength(metric: float, threshold: float) -> float:
    """Factual distance measure: 0.5 exactly at threshold, saturating at 1.0."""
    if threshold <= 0:
        return 0.0
    return min(1.0, abs(metric) / threshold / 2.0)


def _closes(candles: list[Candle]) -> list[float]:
    return [c.close for c in candles]


class MomentumFactor:
    name = "MOMENTUM_EXPANSION"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        candles = facts.candles
        if len(candles) < 61 or facts.last_price is None:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="INSUFFICIENT_CANDLES",
                observed_at=_ts(),
            )

        def ret(n: int) -> float:
            base = candles[-1 - n].close
            return (facts.last_price - base) / base if base else 0.0

        r15, r5, r60 = ret(15), ret(5), ret(60)
        vols = [c.volume for c in candles]
        recent_vol = sum(vols[-5:]) / 5.0
        baseline_vol = sum(vols[-65:-5]) / 60.0 if len(vols) >= 65 else (sum(vols) / len(vols))
        volume_ratio = recent_vol / baseline_vol if baseline_vol > 0 else 0.0
        metric = max(abs(r15), abs(r5) / 2.0)
        triggered = abs(r15) >= self.t.momentum_return_15m or abs(r5) >= self.t.momentum_return_5m
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(metric, self.t.momentum_return_15m), 4) if triggered else None,
            facts={
                "return_5m": round(r5, 6),
                "return_15m": round(r15, 6),
                "return_60m": round(r60, 6),
                "volume_ratio": round(volume_ratio, 4),
            },
            observed_at=_ts(),
        )


class BreakoutFactor:
    name = "BREAKOUT_ATTEMPT"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        candles = facts.candles
        k = self.t.breakout_lookback
        if len(candles) < k + 2 or facts.last_price is None:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="INSUFFICIENT_CANDLES",
                observed_at=_ts(),
            )
        window = candles[-(k + 1) : -1]
        prior_high = max(c.high for c in window)
        prior_low = min(c.low for c in window)
        px = facts.last_price
        location = None
        level = None
        distance = None
        if px > prior_high:
            location = "above_prior_high"
            level, distance = prior_high, (px - prior_high) / prior_high * 10_000.0
        elif px < prior_low:
            location = "below_prior_low"
            level, distance = prior_low, (prior_low - px) / prior_low * 10_000.0
        triggered = location is not None and distance >= self.t.breakout_min_distance_bps
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(
                _strength(
                    (distance or 0.0) / 10_000.0, self.t.breakout_min_distance_bps / 10_000.0
                ),
                4,
            )
            if triggered
            else None,
            facts={
                "location": location,
                "breakout_level": level,
                "distance_bps": round(distance, 2) if distance is not None else None,
                "lookback_bars": k,
            },
            observed_at=_ts(),
        )


class VolumeFactor:
    name = "VOLUME_EXPANSION"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        vols = [c.volume for c in facts.candles]
        n_base, n_recent = self.t.volume_baseline_bars, self.t.volume_recent_bars
        if len(vols) < n_base + n_recent:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="INSUFFICIENT_CANDLES",
                observed_at=_ts(),
            )
        recent = sum(vols[-n_recent:]) / n_recent
        baseline = sum(vols[-(n_base + n_recent) : -n_recent]) / n_base
        if baseline <= 0:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="ZERO_BASELINE",
                observed_at=_ts(),
            )
        ratio = recent / baseline
        triggered = ratio >= self.t.volume_ratio
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(ratio, self.t.volume_ratio), 4) if triggered else None,
            facts={
                "volume_ratio": round(ratio, 4),
                "recent_vol": round(recent, 8),
                "baseline_vol": round(baseline, 8),
            },
            observed_at=_ts(),
        )


class MeanReversionFactor:
    name = "MEAN_REVERSION_SETUP"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        closes = _closes(facts.candles)
        w = self.t.mean_reversion_window
        if len(closes) < w + 1:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="INSUFFICIENT_CANDLES",
                observed_at=_ts(),
            )
        window = closes[-w:]
        sma = sum(window) / w
        var = sum((c - sma) ** 2 for c in window) / w
        std = var**0.5
        last = closes[-1]
        if std <= 0 or sma <= 0:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="ZERO_VARIANCE",
                observed_at=_ts(),
            )
        z = (last - sma) / std
        triggered = abs(z) >= self.t.mean_reversion_zscore
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(z, self.t.mean_reversion_zscore), 4) if triggered else None,
            facts={
                "zscore": round(z, 4),
                "sma": round(sma, 8),
                "distance_bps": round((last - sma) / sma * 10_000.0, 2),
            },
            observed_at=_ts(),
        )


class VolatilityFactor:
    name = "VOLATILITY_EXPANSION"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        closes = _closes(facts.candles)
        n_recent, n_base = self.t.volatility_recent_bars, self.t.volatility_baseline_bars
        if len(closes) < n_base + n_recent + 1:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="INSUFFICIENT_CANDLES",
                observed_at=_ts(),
            )

        def rets(seq: list[float]) -> list[float]:
            return [
                (seq[i] - seq[i - 1]) / seq[i - 1] for i in range(1, len(seq)) if seq[i - 1] > 0
            ]

        recent = rets(closes[-(n_recent + 1) :])
        baseline = rets(closes[-(n_base + n_recent + 1) : -n_recent])
        if not recent or not baseline:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="NO_RETURNS",
                observed_at=_ts(),
            )

        def std(xs: list[float]) -> float:
            m = sum(xs) / len(xs)
            return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5

        r_std, b_std = std(recent), std(baseline)
        if b_std <= 0:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="ZERO_BASELINE_VOL",
                observed_at=_ts(),
            )
        ratio = r_std / b_std
        triggered = ratio >= self.t.volatility_expansion_ratio
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(ratio, self.t.volatility_expansion_ratio), 4)
            if triggered
            else None,
            facts={
                "recent_vol_bps": round(r_std * 10_000.0, 2),
                "baseline_vol_bps": round(b_std * 10_000.0, 2),
                "ratio": round(ratio, 4),
            },
            observed_at=_ts(),
        )


class FundingFactor:
    name = "FUNDING_EXTREME"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        if facts.funding_rate is None:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="NO_FUNDING_FACT",
                observed_at=_ts(),
            )
        fr = facts.funding_rate
        triggered = abs(fr) >= self.t.funding_extreme
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(fr, self.t.funding_extreme), 4) if triggered else None,
            facts={"funding_rate": fr},
            observed_at=_ts(),
        )


class OpenInterestFactor:
    name = "OI_ACCELERATION"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        if facts.oi_change_pct is None or facts.oi_samples < 2:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="INSUFFICIENT_OI_SAMPLES",
                observed_at=_ts(),
            )
        chg = facts.oi_change_pct
        triggered = abs(chg) >= self.t.oi_change_pct
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(chg, self.t.oi_change_pct), 4) if triggered else None,
            facts={"oi_change_pct": round(chg, 4), "samples": facts.oi_samples},
            observed_at=_ts(),
        )


class OrderbookImbalanceFactor:
    name = "ORDERBOOK_IMBALANCE"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        if facts.bid_qty is None or facts.ask_qty is None or facts.ask_qty <= 0:
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="NO_BOOK_QUANTITIES",
                observed_at=_ts(),
            )
        ratio = facts.bid_qty / facts.ask_qty
        triggered = ratio >= self.t.orderbook_imbalance_ratio or ratio <= (
            1.0 / self.t.orderbook_imbalance_ratio
        )
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(ratio, self.t.orderbook_imbalance_ratio), 4)
            if triggered
            else None,
            facts={
                "bid_ask_qty_ratio": round(ratio, 4),
                "bid_qty": facts.bid_qty,
                "ask_qty": facts.ask_qty,
            },
            observed_at=_ts(),
        )


class LiquidityAnomalyFactor:
    name = "LIQUIDITY_ANOMALY"

    def __init__(self, thresholds: FactorThresholds | None = None) -> None:
        self.t = thresholds or FactorThresholds()

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        if facts.volume_24h_usd is None or facts.cohort_median_turnover_usd in (None, 0):
            return FactorObservation(
                symbol=facts.symbol,
                factor=self.name,
                status=UNAVAILABLE,
                unavailable_reason="NO_COHORT_BASELINE",
                observed_at=_ts(),
            )
        ratio = facts.volume_24h_usd / float(facts.cohort_median_turnover_usd)
        triggered = ratio <= self.t.liquidity_anomaly_ratio
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status=TRIGGERED if triggered else NOT_TRIGGERED,
            strength=round(_strength(1.0 - ratio, 1.0 - self.t.liquidity_anomaly_ratio), 4)
            if triggered
            else None,
            facts={"turnover_vs_cohort": round(ratio, 6), "volume_24h_usd": facts.volume_24h_usd},
            observed_at=_ts(),
        )


DEFAULT_FACTORS: tuple = (
    MomentumFactor(),
    BreakoutFactor(),
    VolumeFactor(),
    MeanReversionFactor(),
    VolatilityFactor(),
    FundingFactor(),
    OpenInterestFactor(),
    OrderbookImbalanceFactor(),
    LiquidityAnomalyFactor(),
)

FORBIDDEN_DIRECTION_WORDS = ("LONG", "SHORT", "BUY", "SELL")


def validate_no_direction_semantics(observations: list[FactorObservation]) -> None:
    """Guard §6: factor outputs must never carry directional command semantics."""
    for obs in observations:
        text = f"{obs.factor} {obs.status}".upper()
        for word in FORBIDDEN_DIRECTION_WORDS:
            assert word not in text, f"factor output carries direction semantics: {obs.factor}"
