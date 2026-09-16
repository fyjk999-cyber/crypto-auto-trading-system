"""The 25 factual expert models (Low-Risk V2 Phase 2).

Each model returns a ``ModelEvidence`` record. Models are evidence only: they
never emit an order, never size a position and never bypass the Core LLM.
Missing data produces ``UNAVAILABLE``, never a fabricated direction.
"""

from __future__ import annotations

import math
from typing import Any

from crypto_trader.factors.expert import indicators as ind
from crypto_trader.factors.expert.context import (
    ExpertInputs,
    closes,
    highs,
    lows,
    volumes,
)
from crypto_trader.factors.expert.types import (
    REGIME_LABELS,
    REQUIRED_MODELS,
    EvidenceDirection,
    EvidenceQuality,
    ModelEvidence,
    ModelSpec,
    clamp,
    direction_from_score,
    unavailable,
)

SPEC_BY_ID: dict[str, ModelSpec] = {spec.model_id: spec for spec in REQUIRED_MODELS}


def spec_of(model_id: str) -> ModelSpec:
    return SPEC_BY_ID[model_id]


def _eq_quality(inputs: ExpertInputs) -> EvidenceQuality:
    if inputs.state is None:
        return EvidenceQuality.HEALTHY
    from crypto_trader.market_data.state import DataHealth

    if inputs.state.evidence_quality == DataHealth.HEALTHY:
        return EvidenceQuality.HEALTHY
    return EvidenceQuality.DEGRADED


def _evidence(
    model_id: str,
    inputs: ExpertInputs,
    *,
    score: float,
    confidence: float,
    theory: str,
    model_version: str | None = None,
    support: list[str] | None = None,
    counter: list[str] | None = None,
    neutral: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    timeframes: tuple[str, ...] | None = None,
    regime_compatibility: list[str] | None = None,
    strategy_compatibility: list[str] | None = None,
    entry_use: str = "",
    exit_use: str = "",
    reassessment_use: str = "",
    invalidation: str = "",
    quality: EvidenceQuality | None = None,
) -> ModelEvidence:
    spec = spec_of(model_id)
    return ModelEvidence(
        model_id=spec.model_id,
        model_version=model_version or spec.version,
        family=spec.family,
        symbol=inputs.symbol,
        timeframes=timeframes or spec.timeframes,
        direction=direction_from_score(score),
        direction_score=clamp(score),
        confidence=max(0.0, min(1.0, confidence)),
        theory=theory,
        supporting_evidence=list(support or []),
        counter_evidence=list(counter or []),
        neutral_evidence=list(neutral or []),
        regime_compatibility=list(regime_compatibility or ["*"]),
        strategy_compatibility=list(strategy_compatibility or ["*"]),
        entry_use=entry_use or "evidence only",
        exit_use=exit_use or "evidence only",
        reassessment_use=reassessment_use or "evidence only",
        invalidation=invalidation,
        data_quality=quality or _eq_quality(inputs),
        freshness_seconds=inputs.freshness_seconds,
        metrics=dict(metrics or {}),
    )


def _ohlcv(
    inputs: ExpertInputs, timeframe: str
) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    candles = inputs.series(timeframe)
    return (
        [c.open for c in candles],
        highs(candles),
        lows(candles),
        closes(candles),
        volumes(candles),
    )


def _aligned_structure(
    price: float, ema20: float | None, ema50: float | None, ema200: float | None
) -> float:
    parts: list[float] = []
    for value, weight in ((ema20, 0.35), (ema50, 0.35), (ema200, 0.30)):
        if value is None or value <= 0:
            continue
        parts.append(weight * (1.0 if price > value else -1.0))
    return clamp(sum(parts), -1.0, 1.0)


# --------------------------------------------------------------------------- 01
def model_01_ema_multi_tf(inputs: ExpertInputs) -> ModelEvidence:
    scores: list[float] = []
    details: list[str] = []
    missing: list[str] = []
    for timeframe in ("4h", "1h", "15m"):
        _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
        if len(close_values) < 200:
            missing.append(timeframe)
            continue
        price = close_values[-1]
        e20 = ind.ema(close_values, 20)[-1]
        e50 = ind.ema(close_values, 50)[-1]
        e200 = ind.ema(close_values, 200)[-1]
        score = _aligned_structure(price, e20, e50, e200)
        scores.append(score)
        details.append(
            f"{timeframe}: px_vs_ema={score:+.2f} e20/50/200={e20:.4g}/{e50:.4g}/{e200:.4g}"
        )
    if not scores:
        return unavailable(
            spec_of("01_EMA_MULTI_TF"), inputs.symbol, f"insufficient history: {','.join(missing)}"
        )
    score = sum(scores) / len(scores)
    consistency = abs(score)
    return _evidence(
        "01_EMA_MULTI_TF",
        inputs,
        score=score,
        confidence=0.4 + 0.5 * consistency * (len(scores) / 3.0),
        theory="EMA 20/50/200 alignment across 4h/1h/15m describes trend structure.",
        support=details if score > 0 else [],
        counter=details if score < 0 else [],
        neutral=details if abs(score) <= 0.15 else [],
        metrics={
            "timeframe_scores": dict(zip(("4h", "1h", "15m"), scores, strict=False)),
            "timeframes_evaluated": len(scores),
        },
        entry_use="trend confirmation for TREND_FOLLOWING/PULLBACK entries",
        exit_use="structure flip evidence for Base Exit review",
        reassessment_use="EMA alignment change is a material trend event",
        invalidation="price crosses back through the 50/200 EMA cluster",
    )


# --------------------------------------------------------------------------- 02
def model_02_macd(inputs: ExpertInputs) -> ModelEvidence:
    for timeframe in ("1h", "15m"):
        _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
        if len(close_values) < 35:
            continue
        line, signal, histogram = ind.macd(close_values)
        if not histogram:
            continue
        last = histogram[-1]
        previous = histogram[-2] if len(histogram) >= 2 else 0.0
        acceleration = last - previous
        atr_values = ind.atr(*_ohlcv(inputs, timeframe)[1:4], 14)
        scale = (atr_values[-1] if atr_values else close_values[-1] * 0.005) or 1.0
        normalized = last / scale
        accel_norm = acceleration / scale
        score = clamp(normalized * 2.0 + accel_norm * 1.5)
        return _evidence(
            "02_MACD",
            inputs,
            score=score,
            confidence=min(0.95, 0.35 + 0.6 * min(1.0, abs(score))),
            theory="MACD 12/26/9 histogram sign and acceleration measure momentum change.",
            support=[f"{timeframe} histogram={last:.6g} acceleration={acceleration:.6g}"]
            if score > 0
            else [],
            counter=[f"{timeframe} histogram={last:.6g} acceleration={acceleration:.6g}"]
            if score < 0
            else [],
            neutral=[f"{timeframe} histogram={last:.6g}"]
            if direction_from_score(score) == EvidenceDirection.NEUTRAL
            else [],
            metrics={
                "timeframe": timeframe,
                "macd_line": line[-1],
                "signal": signal[-1],
                "histogram": last,
                "acceleration": acceleration,
            },
            entry_use="momentum confirmation and divergence awareness",
            exit_use="histogram flip against position is exit review evidence",
            reassessment_use="histogram acceleration reversal is a material momentum event",
            invalidation="histogram crosses zero against the thesis",
        )
    return unavailable(spec_of("02_MACD"), inputs.symbol, "insufficient history for MACD")


# --------------------------------------------------------------------------- 03
def model_03_adx_di(inputs: ExpertInputs) -> ModelEvidence:
    for timeframe in ("1h", "15m"):
        _, high_values, low_values, close_values, _ = _ohlcv(inputs, timeframe)
        if len(close_values) < 30:
            continue
        adx_values, plus, minus = ind.adx_di(high_values, low_values, close_values, 14)
        if not adx_values:
            continue
        adx = adx_values[-1]
        plus_last, minus_last = plus[-1], minus[-1]
        raw = (plus_last - minus_last) / 100.0
        trend_weight = min(1.0, adx / 40.0)
        score = clamp(raw * trend_weight * 2.0)
        return _evidence(
            "03_ADX_DI",
            inputs,
            score=score,
            confidence=min(0.95, 0.3 + 0.6 * trend_weight),
            theory="ADX/DI 14 measures directional trend strength.",
            support=[f"{timeframe} adx={adx:.2f} +DI={plus_last:.2f} -DI={minus_last:.2f}"]
            if score > 0
            else [],
            counter=[f"{timeframe} adx={adx:.2f} +DI={plus_last:.2f} -DI={minus_last:.2f}"]
            if score < 0
            else [],
            neutral=[f"{timeframe} adx={adx:.2f} (weak trend)"] if trend_weight < 0.5 else [],
            metrics={
                "timeframe": timeframe,
                "adx": adx,
                "plus_di": plus_last,
                "minus_di": minus_last,
            },
            entry_use="trend strength gate for TREND_FOLLOWING",
            exit_use="trend exhaustion evidence for Base Exit review",
            reassessment_use="DI crossover or ADX regime shift is a material trend event",
            invalidation="DI cross against thesis with ADX>25",
        )
    return unavailable(spec_of("03_ADX_DI"), inputs.symbol, "insufficient history for ADX/DI")


# --------------------------------------------------------------------------- 04
def model_04_rsi_context(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
    if len(close_values) < 20:
        return unavailable(spec_of("04_RSI_CONTEXT"), inputs.symbol, "insufficient history for RSI")
    rsi_values = ind.rsi(close_values, 14)
    if not rsi_values:
        return unavailable(spec_of("04_RSI_CONTEXT"), inputs.symbol, "RSI undefined")
    rsi = rsi_values[-1]
    regime = str(inputs.extra.get("regime", "UNCERTAIN"))
    if rsi >= 70:
        score = 0.6 if regime in ("TREND_UP", "BREAKOUT_EXPANSION") else -0.7
    elif rsi <= 30:
        score = -0.6 if regime in ("TREND_DOWN",) else 0.7
    else:
        score = (rsi - 50.0) / 50.0 * 0.3
    return _evidence(
        "04_RSI_CONTEXT",
        inputs,
        score=score,
        confidence=0.45 + 0.3 * min(1.0, abs(rsi - 50.0) / 50.0),
        theory="RSI 14 with regime-aware interpretation (trend continuation vs mean reversion).",
        support=[f"RSI14={rsi:.2f} in regime {regime}"] if score > 0 else [],
        counter=[f"RSI14={rsi:.2f} in regime {regime}"] if score < 0 else [],
        neutral=[f"RSI14={rsi:.2f} mid-range"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={"timeframe": timeframe, "rsi": rsi, "regime": regime},
        regime_compatibility=["TREND_UP", "TREND_DOWN", "RANGE", "BREAKOUT_EXPANSION"],
        entry_use="entry timing; overbought/oversold context only",
        exit_use="RSI extremes against position support exit review",
        reassessment_use="RSI regime transition is a material oscillator event",
        invalidation="RSI returns to mid-range without price follow-through",
    )


# --------------------------------------------------------------------------- 05
def model_05_bollinger_regime(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "1h"
    _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
    bands = ind.bollinger(close_values, 20, 2.0)
    if not bands:
        return unavailable(
            spec_of("05_BOLLINGER_REGIME"), inputs.symbol, "insufficient history for Bollinger"
        )
    middle, upper, lower = bands[-1]
    width = upper - lower
    if width <= 0:
        return unavailable(spec_of("05_BOLLINGER_REGIME"), inputs.symbol, "zero bandwidth")
    percent_b = (close_values[-1] - lower) / width
    bandwidth_pct = width / middle * 100.0 if middle > 0 else 0.0
    previous_width = bands[-2][1] - bands[-2][2] if len(bands) >= 2 else width
    expanding = width > previous_width
    score = clamp(-(percent_b - 0.5) * 2.0 * (0.8 if not expanding else 0.5))
    return _evidence(
        "05_BOLLINGER_REGIME",
        inputs,
        score=score,
        confidence=0.4 + 0.3 * min(1.0, abs(percent_b - 0.5) * 2.0),
        theory="Bollinger 20/2σ position and bandwidth expansion regime.",
        support=[f"%B={percent_b:.3f} bandwidth={bandwidth_pct:.3f}% expanding={expanding}"]
        if score > 0
        else [],
        counter=[f"%B={percent_b:.3f} bandwidth={bandwidth_pct:.3f}% expanding={expanding}"]
        if score < 0
        else [],
        neutral=[f"%B={percent_b:.3f} mid-band"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={
            "timeframe": timeframe,
            "percent_b": percent_b,
            "bandwidth_pct": bandwidth_pct,
            "expanding": expanding,
        },
        regime_compatibility=["RANGE", "BREAKOUT_EXPANSION", "HIGH_VOLATILITY"],
        entry_use="mean-reversion vs breakout regime selection",
        exit_use="band walk exhaustion for Base Exit review",
        reassessment_use="bandwidth regime change is a material volatility event",
        invalidation="sustained closes outside the band with expanding width",
    )


# --------------------------------------------------------------------------- 06
def model_06_vwap_deviation(inputs: ExpertInputs) -> ModelEvidence:
    for timeframe in ("1h", "15m"):
        candles = inputs.series(timeframe)
        if len(candles) < 24:
            continue
        window = candles[-96:] if timeframe == "15m" else candles[-24:]
        volume_sum = sum(item.volume for item in window)
        if volume_sum <= 0:
            continue
        typical = sum(((item.high + item.low + item.close) / 3.0) * item.volume for item in window)
        vwap = typical / volume_sum
        price = closes(candles)[-1]
        atr_values = ind.atr(highs(candles), lows(candles), closes(candles), 14)
        scale = (atr_values[-1] / price) if atr_values and price > 0 else 0.01
        deviation = (price - vwap) / vwap if vwap > 0 else 0.0
        score = clamp(-deviation / max(scale, 1e-6) * 0.5)
        return _evidence(
            "06_VWAP_DEVIATION",
            inputs,
            score=score,
            confidence=0.4 + 0.3 * min(1.0, abs(score)),
            theory="Deviation from rolling VWAP is a mean-reversion anchor.",
            support=[f"{timeframe} price={price:.6g} vwap={vwap:.6g} dev={deviation * 100:.3f}%"]
            if score > 0
            else [],
            counter=[f"{timeframe} price={price:.6g} vwap={vwap:.6g} dev={deviation * 100:.3f}%"]
            if score < 0
            else [],
            neutral=[f"{timeframe} price near VWAP"]
            if direction_from_score(score) == EvidenceDirection.NEUTRAL
            else [],
            metrics={
                "timeframe": timeframe,
                "vwap": vwap,
                "deviation_pct": deviation * 100.0,
                "atr_pct": scale * 100.0,
            },
            regime_compatibility=["RANGE", "TREND_UP", "TREND_DOWN"],
            entry_use="VWAP_REVERSION entry anchor",
            exit_use="VWAP reclaim/loss evidence for exits",
            reassessment_use="large VWAP dislocation is a material mean-reversion event",
            invalidation="price holds beyond VWAP for two consecutive bars against thesis",
        )
    return unavailable(spec_of("06_VWAP_DEVIATION"), inputs.symbol, "insufficient history for VWAP")


# --------------------------------------------------------------------------- 07
def model_07_atr_natr(inputs: ExpertInputs) -> ModelEvidence:
    for timeframe in ("1h", "15m"):
        _, high_values, low_values, close_values, _ = _ohlcv(inputs, timeframe)
        atr_values = ind.atr(high_values, low_values, close_values, 14)
        natr_values = ind.natr(high_values, low_values, close_values, 14)
        if not atr_values:
            continue
        natr = natr_values[-1] if natr_values else 0.0
        atr_pct = atr_values[-1] / close_values[-1] * 100.0 if close_values[-1] > 0 else 0.0
        quality = EvidenceQuality.HEALTHY if len(close_values) >= 30 else EvidenceQuality.DEGRADED
        return _evidence(
            "07_ATR_NATR",
            inputs,
            score=0.0,
            confidence=min(0.9, 0.4 + len(close_values) / 200.0),
            theory="ATR/NATR 14 measures factual volatility; direction neutral.",
            neutral=[f"{timeframe} ATR%={atr_pct:.3f} NATR={natr:.3f}"],
            metrics={
                "timeframe": timeframe,
                "atr": atr_values[-1],
                "atr_pct": atr_pct,
                "natr": natr,
            },
            entry_use="volatility normalization for size/stop planning",
            exit_use="volatility regime input for Fast Profit and Risk exits",
            reassessment_use="ATR expansion/contraction is a material volatility event",
            invalidation="n/a (volatility context model)",
            quality=quality,
        )
    return unavailable(spec_of("07_ATR_NATR"), inputs.symbol, "insufficient history for ATR")


# --------------------------------------------------------------------------- 08
def model_08_volume_breakout(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    candles = inputs.series(timeframe)
    if len(candles) < 25:
        return unavailable(
            spec_of("08_VOLUME_BREAKOUT"), inputs.symbol, "insufficient history for volume breakout"
        )
    recent_volume = candles[-1].volume
    baseline = sum(c.volume for c in candles[-21:-1]) / 20.0
    rvol = recent_volume / baseline if baseline > 0 else 0.0
    prior_high = max(c.high for c in candles[-21:-1])
    prior_low = min(c.low for c in candles[-21:-1])
    price = candles[-1].close
    breakout_up = price > prior_high
    breakout_down = price < prior_low
    confirmation = min(1.0, rvol / 2.5)
    if breakout_up:
        score = 0.5 + 0.5 * confirmation
    elif breakout_down:
        score = -(0.5 + 0.5 * confirmation)
    else:
        score = 0.0
    return _evidence(
        "08_VOLUME_BREAKOUT",
        inputs,
        score=score,
        confidence=0.35 + 0.5 * confirmation if score else 0.3,
        theory="Relative volume with 20-bar range breakout measures participation.",
        support=[f"breakout_up={breakout_up} RVOL={rvol:.2f}"] if score > 0 else [],
        counter=[f"breakout_down={breakout_down} RVOL={rvol:.2f}"] if score < 0 else [],
        neutral=[f"inside 20-bar range RVOL={rvol:.2f}"] if score == 0 else [],
        metrics={
            "timeframe": timeframe,
            "rvol": rvol,
            "prior_high": prior_high,
            "prior_low": prior_low,
            "breakout_up": breakout_up,
            "breakout_down": breakout_down,
        },
        strategy_compatibility=["BREAKOUT", "MOMENTUM"],
        entry_use="BREAKOUT entry confirmation",
        exit_use="volume climax/failure evidence for exits",
        reassessment_use="RVOL surge is a material volume event",
        invalidation="price re-enters the prior range without volume follow-through",
    )


# --------------------------------------------------------------------------- 09
def model_09_cvd_taker_flow(inputs: ExpertInputs) -> ModelEvidence:
    if inputs.state is None:
        return unavailable(spec_of("09_CVD_TAKER_FLOW"), inputs.symbol, "no factual market state")
    state = inputs.state
    if state.cvd is None or state.taker_buy_volume is None or state.taker_sell_volume is None:
        return unavailable(spec_of("09_CVD_TAKER_FLOW"), inputs.symbol, "no factual trades stream")
    total = state.taker_buy_volume + state.taker_sell_volume
    if total <= 0:
        return unavailable(spec_of("09_CVD_TAKER_FLOW"), inputs.symbol, "zero taker volume")
    ratio = float(state.cvd) / float(total)
    score = clamp(ratio * 1.5)
    confidence = min(0.9, 0.35 + min(1.0, state.trade_count / 100.0) * 0.4)
    return _evidence(
        "09_CVD_TAKER_FLOW",
        inputs,
        score=score,
        confidence=confidence,
        theory="Taker buy/sell volume and CVD measure aggressive flow imbalance.",
        support=[
            f"CVD={state.cvd} b={state.taker_buy_volume} "
            f"s={state.taker_sell_volume} n={state.trade_count}"
        ]
        if score > 0
        else [],
        counter=[
            f"CVD={state.cvd} b={state.taker_buy_volume} "
            f"s={state.taker_sell_volume} n={state.trade_count}"
        ]
        if score < 0
        else [],
        neutral=[f"CVD≈0 ({state.trade_count} trades)"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={
            "cvd": float(state.cvd),
            "taker_buy_volume": float(state.taker_buy_volume),
            "taker_sell_volume": float(state.taker_sell_volume),
            "trade_count": state.trade_count,
            "window_seconds": state.trades_window_seconds,
            "large_trade_count": state.large_trade_count,
        },
        quality=EvidenceQuality.HEALTHY if state.trade_count >= 20 else EvidenceQuality.DEGRADED,
        entry_use="order-flow confirmation for entry timing",
        exit_use="CVD reversal is Fast Profit / exit review evidence",
        reassessment_use="CVD reversal is a material order-flow event",
        invalidation="CVD flips sign against the thesis",
    )


# --------------------------------------------------------------------------- 10
def model_10_price_oi(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    close_values = closes(inputs.series(timeframe))
    if len(close_values) < 5 or inputs.state is None:
        return unavailable(spec_of("10_PRICE_OI"), inputs.symbol, "no factual price/OI state")
    price_change = close_values[-1] / close_values[-5] - 1.0 if close_values[-5] > 0 else 0.0
    oi_change = inputs.state.open_interest_change
    if oi_change is None:
        return unavailable(
            spec_of("10_PRICE_OI"), inputs.symbol, "no factual OI change (needs two samples)"
        )
    oi_pct = float(oi_change / inputs.state.open_interest) if inputs.state.open_interest else 0.0
    if price_change > 0 and oi_pct > 0:
        score = 0.8
        note = "price up + OI up: new long positioning"
    elif price_change < 0 and oi_pct > 0:
        score = -0.8
        note = "price down + OI up: new short positioning"
    elif price_change > 0 and oi_pct < 0:
        score = -0.3
        note = "price up + OI down: short covering, weaker rally"
    elif price_change < 0 and oi_pct < 0:
        score = 0.3
        note = "price down + OI down: long liquidation exhaustion"
    else:
        score = 0.0
        note = "flat price/OI"
    return _evidence(
        "10_PRICE_OI",
        inputs,
        score=score,
        confidence=0.45,
        theory="Price change together with OI change distinguishes conviction vs liquidation.",
        support=[note] if score > 0 else [],
        counter=[note] if score < 0 else [],
        neutral=[note] if score == 0 else [],
        metrics={
            "timeframe": timeframe,
            "price_change_pct": price_change * 100.0,
            "oi_change_pct": oi_pct * 100.0,
            "note": note,
        },
        entry_use="positioning confirmation for entries",
        exit_use="OI divergence against position supports exit review",
        reassessment_use="OI/price divergence is a material positioning event",
        invalidation="OI change normalizes without price follow-through",
    )


# --------------------------------------------------------------------------- 11
def model_11_sma_structure(inputs: ExpertInputs) -> ModelEvidence:
    scores: list[float] = []
    details: list[str] = []
    for timeframe in ("4h", "1h"):
        _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
        if len(close_values) < 200:
            continue
        price = close_values[-1]
        s20 = ind.sma(close_values, 20)[-1]
        s50 = ind.sma(close_values, 50)[-1]
        s200 = ind.sma(close_values, 200)[-1]
        scores.append(_aligned_structure(price, s20, s50, s200))
        details.append(
            f"{timeframe}: price={price:.6g} sma20={s20:.6g} sma50={s50:.6g} sma200={s200:.6g}"
        )
    if not scores:
        return unavailable(
            spec_of("11_SMA_STRUCTURE"), inputs.symbol, "insufficient history for SMA structure"
        )
    score = sum(scores) / len(scores)
    return _evidence(
        "11_SMA_STRUCTURE",
        inputs,
        score=score,
        confidence=0.4 + 0.4 * min(1.0, abs(score)),
        theory="SMA 20/50/200 alignment describes slower structural trend.",
        support=details if score > 0 else [],
        counter=details if score < 0 else [],
        neutral=details if abs(score) <= 0.15 else [],
        metrics={"timeframe_scores": dict(zip(("4h", "1h"), scores, strict=False))},
        entry_use="higher-timeframe structure confirmation",
        exit_use="structure break evidence for Base Exit",
        reassessment_use="SMA alignment flip is a material structure event",
        invalidation="price crosses the 200 SMA against thesis",
    )


# --------------------------------------------------------------------------- 12
def model_12_supertrend(inputs: ExpertInputs) -> ModelEvidence:
    for timeframe in ("1h", "15m"):
        _, high_values, low_values, close_values, _ = _ohlcv(inputs, timeframe)
        bands = ind.supertrend(high_values, low_values, close_values, 10, 3.0)
        if not bands:
            continue
        line, trend = bands[-1]
        atr_values = ind.atr(high_values, low_values, close_values, 10)
        distance = (
            abs(close_values[-1] - line) / atr_values[-1]
            if atr_values and atr_values[-1] > 0
            else 0.0
        )
        score = (1.0 if trend > 0 else -1.0) * min(1.0, 0.5 + distance * 0.2)
        return _evidence(
            "12_SUPERTREND",
            inputs,
            score=score,
            confidence=min(0.9, 0.4 + 0.3 * min(1.0, distance)),
            theory="SuperTrend (ATR10×3) trailing regime direction.",
            support=[f"{timeframe} SuperTrend up, line={line:.6g}"] if trend > 0 else [],
            counter=[f"{timeframe} SuperTrend down, line={line:.6g}"] if trend < 0 else [],
            metrics={
                "timeframe": timeframe,
                "line": line,
                "trend": trend,
                "distance_atr": distance,
            },
            strategy_compatibility=["TREND_FOLLOWING", "BREAKOUT", "MOMENTUM"],
            entry_use="trailing trend filter",
            exit_use="SuperTrend flip is exit review evidence",
            reassessment_use="SuperTrend flip is a material trend event",
            invalidation="price closes through the SuperTrend line",
        )
    return unavailable(
        spec_of("12_SUPERTREND"), inputs.symbol, "insufficient history for SuperTrend"
    )


# --------------------------------------------------------------------------- 13
def model_13_stoch_rsi(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
    if len(close_values) < 35:
        return unavailable(
            spec_of("13_STOCH_RSI"), inputs.symbol, "insufficient history for StochRSI"
        )
    k_line, d_line = ind.stochastic_rsi(close_values)
    if not k_line:
        return unavailable(spec_of("13_STOCH_RSI"), inputs.symbol, "StochRSI undefined")
    k = k_line[-1]
    d = d_line[-1] if d_line else k
    score = clamp((k - 50.0) / 50.0 * 0.6 + ((k - d) / 50.0) * 0.4)
    return _evidence(
        "13_STOCH_RSI",
        inputs,
        score=score,
        confidence=0.4 + 0.25 * min(1.0, abs(k - 50.0) / 50.0),
        theory="Stochastic RSI 14/14/3/3 entry timing oscillator.",
        support=[f"K={k:.2f} D={d:.2f}"] if score > 0 else [],
        counter=[f"K={k:.2f} D={d:.2f}"] if score < 0 else [],
        neutral=[f"K={k:.2f} mid-range"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={"timeframe": timeframe, "k": k, "d": d},
        strategy_compatibility=["PULLBACK", "MEAN_REVERSION", "MOMENTUM"],
        entry_use="short-term entry timing",
        exit_use="oscillator exhaustion evidence",
        reassessment_use="K/D extreme cross is a timing event",
        invalidation="K crosses back through D against thesis",
    )


# --------------------------------------------------------------------------- 14
def model_14_roc(inputs: ExpertInputs) -> ModelEvidence:
    scores: list[float] = []
    details: list[str] = []
    for timeframe in ("1h", "15m"):
        _, _, _, close_values, _ = _ohlcv(inputs, timeframe)
        values = ind.roc(close_values, 12)
        if not values:
            continue
        value = values[-1]
        scores.append(clamp(value / 3.0))
        details.append(f"{timeframe} ROC12={value:.3f}%")
    if not scores:
        return unavailable(spec_of("14_ROC"), inputs.symbol, "insufficient history for ROC")
    score = sum(scores) / len(scores)
    return _evidence(
        "14_ROC",
        inputs,
        score=score,
        confidence=0.4 + 0.3 * min(1.0, abs(score)),
        theory="Rate of change 12 measures raw momentum.",
        support=details if score > 0 else [],
        counter=details if score < 0 else [],
        neutral=details if abs(score) <= 0.15 else [],
        metrics={"roc_details": details},
        entry_use="momentum magnitude confirmation",
        exit_use="momentum decay evidence",
        reassessment_use="ROC sign flip is a material momentum event",
        invalidation="ROC crosses zero against thesis",
    )


# --------------------------------------------------------------------------- 15
def model_15_cci(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    _, high_values, low_values, close_values, _ = _ohlcv(inputs, timeframe)
    values = ind.cci(high_values, low_values, close_values, 20)
    if not values:
        return unavailable(spec_of("15_CCI"), inputs.symbol, "insufficient history for CCI")
    value = values[-1]
    score = clamp(value / 200.0)
    return _evidence(
        "15_CCI",
        inputs,
        score=score,
        confidence=0.35 + 0.3 * min(1.0, abs(value) / 200.0),
        theory="CCI 20 measures deviations from the typical-price mean.",
        support=[f"CCI20={value:.2f}"] if score > 0 else [],
        counter=[f"CCI20={value:.2f}"] if score < 0 else [],
        neutral=[f"CCI20={value:.2f}"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={"timeframe": timeframe, "cci": value},
        entry_use="oscillator confirmation",
        exit_use="CCI reversal evidence",
        reassessment_use="CCI crosses ±100 with price confirmation",
        invalidation="CCI returns inside ±100",
    )


# --------------------------------------------------------------------------- 16
def model_16_price_zscore(inputs: ExpertInputs) -> ModelEvidence:
    scores: list[float] = []
    details: list[str] = []
    for timeframe, period in (("1h", 50), ("15m", 100)):
        close_values = closes(inputs.series(timeframe))
        value = ind.zscore(close_values, period)
        if value is None:
            continue
        scores.append(clamp(-value / 3.0))
        details.append(f"{timeframe} z({period})={value:.2f}")
    if not scores:
        return unavailable(
            spec_of("16_PRICE_ZSCORE"), inputs.symbol, "insufficient history for z-score"
        )
    score = sum(scores) / len(scores)
    return _evidence(
        "16_PRICE_ZSCORE",
        inputs,
        score=score,
        confidence=0.4 + 0.3 * min(1.0, abs(score)),
        theory="Price z-score vs SMA50/100 identifies statistical stretch.",
        support=details if score > 0 else [],
        counter=details if score < 0 else [],
        neutral=details if abs(score) <= 0.15 else [],
        metrics={"zscore_details": details},
        strategy_compatibility=["MEAN_REVERSION", "VWAP_REVERSION", "SUPPORT_REBOUND"],
        entry_use="mean-reversion stretch confirmation",
        exit_use="z-score normalization supports exit review",
        reassessment_use="|z|>2.5 is a material mean-reversion event",
        invalidation="z-score continues beyond 3σ with expanding volatility",
    )


# --------------------------------------------------------------------------- 17
def model_17_support_resistance(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "1h"
    candles = inputs.series(timeframe)
    if len(candles) < 40:
        return unavailable(
            spec_of("17_SUPPORT_RESISTANCE"), inputs.symbol, "insufficient history for S/R"
        )
    close_values = closes(candles)
    levels = ind.swing_levels(highs(candles), lows(candles), close_values, 20)
    hvn, lvn = ind.volume_profile_levels(close_values, volumes(candles), 12)
    price = close_values[-1]
    score = 0.0
    notes: list[str] = []
    if levels.support and levels.nearest_support_distance_pct is not None:
        notes.append(
            f"support={levels.support:.6g} ({levels.nearest_support_distance_pct:.2f}% away)"
        )
        if levels.nearest_support_distance_pct < 0.5:
            score += 0.6
    if levels.resistance and levels.nearest_resistance_distance_pct is not None:
        notes.append(
            f"resistance={levels.resistance:.6g} dist={levels.nearest_resistance_distance_pct:.2f}%"
        )
        if levels.nearest_resistance_distance_pct < 0.5:
            score -= 0.6
    if levels.resistance and price > levels.resistance:
        score = 0.8
        notes.append("price broke above prior swing resistance")
    elif levels.support and price < levels.support:
        score = -0.8
        notes.append("price broke below prior swing support")
    score = clamp(score)
    return _evidence(
        "17_SUPPORT_RESISTANCE",
        inputs,
        score=score,
        confidence=0.4 + 0.3 * min(1.0, abs(score)) if score else 0.3,
        theory="Swing + volume-profile support/resistance proximity and breaks.",
        support=notes if score > 0 else [],
        counter=notes if score < 0 else [],
        neutral=notes if score == 0 else [],
        metrics={
            "timeframe": timeframe,
            "support": levels.support,
            "resistance": levels.resistance,
            "hvn": hvn,
            "lvn": lvn,
            "notes": notes,
        },
        strategy_compatibility=["SUPPORT_REBOUND", "BREAKOUT", "MEAN_REVERSION"],
        entry_use="level-based entry planning",
        exit_use="level break supports Base Exit review",
        reassessment_use="level break/reclaim is a material structure event",
        invalidation="price accepts beyond the level on volume",
    )


# --------------------------------------------------------------------------- 18
def model_18_obv(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    _, _, _, close_values, volume_values = _ohlcv(inputs, timeframe)
    if len(close_values) < 30:
        return unavailable(spec_of("18_OBV"), inputs.symbol, "insufficient history for OBV")
    values = ind.obv(close_values, volume_values)
    slope = ind.linear_slope(values, 20)
    average_volume = sum(volume_values[-20:]) / 20.0
    normalized = slope / average_volume if slope is not None and average_volume > 0 else 0.0
    score = clamp(normalized * 0.25)
    return _evidence(
        "18_OBV",
        inputs,
        score=score,
        confidence=0.4 + 0.25 * min(1.0, abs(score)),
        theory="On-balance volume slope measures cumulative volume pressure.",
        support=[f"OBV slope={slope:.3g} normalized={normalized:.3f}"] if score > 0 else [],
        counter=[f"OBV slope={slope:.3g} normalized={normalized:.3f}"] if score < 0 else [],
        neutral=[f"OBV flat (normalized={normalized:.3f})"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={"timeframe": timeframe, "slope": slope, "normalized": normalized},
        entry_use="volume-pressure confirmation",
        exit_use="OBV divergence against price supports exit review",
        reassessment_use="OBV/price divergence is a material volume event",
        invalidation="OBV slope flips sign against thesis",
    )


# --------------------------------------------------------------------------- 19
def model_19_mfi(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    _, high_values, low_values, close_values, volume_values = _ohlcv(inputs, timeframe)
    values = ind.mfi(high_values, low_values, close_values, volume_values, 14)
    if not values:
        return unavailable(spec_of("19_MFI"), inputs.symbol, "insufficient history for MFI")
    value = values[-1]
    if value >= 80:
        score = -0.6
    elif value <= 20:
        score = 0.6
    else:
        score = (value - 50.0) / 50.0 * 0.3
    return _evidence(
        "19_MFI",
        inputs,
        score=score,
        confidence=0.4 + 0.3 * min(1.0, abs(value - 50.0) / 50.0),
        theory="MFI 14 combines price and volume for overbought/oversold flow.",
        support=[f"MFI14={value:.2f}"] if score > 0 else [],
        counter=[f"MFI14={value:.2f}"] if score < 0 else [],
        neutral=[f"MFI14={value:.2f}"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={"timeframe": timeframe, "mfi": value},
        entry_use="flow-aware oscillator timing",
        exit_use="MFI exhaustion supports exit review",
        reassessment_use="MFI extreme reversal is a material flow event",
        invalidation="MFI returns to 50 without price follow-through",
    )


# --------------------------------------------------------------------------- 20
def model_20_cmf(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "15m"
    _, high_values, low_values, close_values, volume_values = _ohlcv(inputs, timeframe)
    values = ind.cmf(high_values, low_values, close_values, volume_values, 20)
    if not values:
        return unavailable(spec_of("20_CMF"), inputs.symbol, "insufficient history for CMF")
    value = values[-1]
    score = clamp(value * 10.0)
    return _evidence(
        "20_CMF",
        inputs,
        score=score,
        confidence=0.4 + 0.25 * min(1.0, abs(value) * 10.0),
        theory="Chaikin Money Flow 20 measures accumulation/distribution pressure.",
        support=[f"CMF20={value:.4f}"] if score > 0 else [],
        counter=[f"CMF20={value:.4f}"] if score < 0 else [],
        neutral=[f"CMF20={value:.4f}"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={"timeframe": timeframe, "cmf": value},
        entry_use="accumulation/distribution confirmation",
        exit_use="distribution divergence supports exit review",
        reassessment_use="CMF sign flip is a material flow event",
        invalidation="CMF flips sign against thesis",
    )


# --------------------------------------------------------------------------- 21
def _runtime_21_features(inputs: ExpertInputs) -> dict[str, Any]:
    """Build the #21 feature dict from the same factual inputs used at runtime."""
    state = inputs.state
    close_values = closes(inputs.series("15m"))
    price = close_values[-1] if close_values else None
    velocity = 0.0
    if len(close_values) >= 6 and close_values[-6] > 0:
        velocity = close_values[-1] / close_values[-6] - 1.0
    change_24h = None
    if len(close_values) >= 97 and close_values[-97] > 0:
        change_24h = (close_values[-1] / close_values[-97] - 1.0) * 100.0

    def _float(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    if state is None:
        return {
            "price": price,
            "price_velocity": velocity,
            "price_change_24h_pct": change_24h,
        }
    return {
        "price": price,
        "best_bid": _float(state.best_bid),
        "best_ask": _float(state.best_ask),
        "bid_qty": _float(state.bid_size),
        "ask_qty": _float(state.ask_size),
        "spread_bps": _float(state.spread_bps),
        "l1_imbalance": _float(state.imbalance_l1),
        "l5_imbalance": _float(state.imbalance_l5),
        "microprice": _float(state.microprice),
        "cvd": _float(state.cvd),
        "taker_buy_volume": _float(state.taker_buy_volume),
        "taker_sell_volume": _float(state.taker_sell_volume),
        "trade_count": state.trade_count,
        "trade_notional_window_usd": _float(state.trade_notional),
        "large_trade_count": state.large_trade_count,
        "open_interest": _float(state.open_interest),
        "oi_change_pct": _float(state.open_interest_change),
        "funding_rate": _float(state.funding_rate),
        "price_change_24h_pct": change_24h,
        "price_velocity": velocity,
        "relative_volume": None,
    }


def _active_artifact_failure(inputs: ExpertInputs, reason: str) -> ModelEvidence:
    """Explicitly degrade #21 evidence when ACTIVE cannot be verified.

    The provisional proxy is deliberately not used: the registry claimed a
    trained artifact and a corrupt artifact must fail closed.
    """
    result = unavailable(
        spec_of("21_ORDER_FLOW_ML"),
        inputs.symbol,
        f"ACTIVE_ARTIFACT_INTEGRITY_FAILED:{reason}",
    )
    result.metrics.update(
        {
            "artifact_status": "ACTIVE_ARTIFACT_INTEGRITY_FAILED",
            "artifact_failure": reason,
        }
    )
    return result


def model_21_order_flow_ml(inputs: ExpertInputs) -> ModelEvidence:
    """Runtime #21 evidence: verified ACTIVE trained artifact when available,
    otherwise the explicitly-labelled provisional engineering proxy."""
    resolver = inputs.extra.get("model_runtime")
    if resolver is not None and callable(getattr(resolver, "resolve_active", None)):
        try:
            loaded = resolver.resolve_active("21_ORDER_FLOW_ML")
        except Exception as exc:
            return _active_artifact_failure(inputs, str(exc))
        if loaded is not None:
            try:
                probability = loaded.predict(_runtime_21_features(inputs))
            except Exception as exc:
                return _active_artifact_failure(inputs, f"PREDICT_FAILED:{exc}")
            score = (probability - 0.5) * 2.0
            confidence = min(0.9, 0.4 + abs(score) * 0.5)
            return _evidence(
                "21_ORDER_FLOW_ML",
                inputs,
                score=score,
                confidence=confidence,
                model_version=loaded.model_version,
                theory="ACTIVE trained order-flow artifact (chronological validation).",
                support=[f"P(up)={probability:.3f}"]
                if score > 0
                else [],
                counter=[f"P(up)={probability:.3f}"] if score < 0 else [],
                neutral=[f"P(up)={probability:.3f}"]
                if direction_from_score(score) == EvidenceDirection.NEUTRAL
                else [],
                metrics={
                    "artifact_status": "ACTIVE_TRAINED_ARTIFACT",
                    "artifact_hash": loaded.artifact_hash,
                    "dataset_version": loaded.dataset_version,
                    "feature_version": loaded.feature_version,
                    "feature_schema_hash": loaded.feature_schema_hash,
                    "label_version": loaded.label_version,
                    "training_cutoff_ts": loaded.training_cutoff_ts,
                    "algorithm": loaded.algorithm,
                    "probability_up": probability,
                },
                quality=EvidenceQuality.HEALTHY,
                entry_use="ACTIVE trained order-flow probability evidence",
                exit_use="ACTIVE trained order-flow reversal evidence",
                reassessment_use="ACTIVE probability regime shift is a material flow event",
                invalidation="ACTIVE artifact unavailable or degraded",
            )
    if inputs.state is None:
        return unavailable(spec_of("21_ORDER_FLOW_ML"), inputs.symbol, "no factual market state")
    state = inputs.state
    if state.cvd is None or state.taker_buy_volume is None or state.taker_sell_volume is None:
        return unavailable(spec_of("21_ORDER_FLOW_ML"), inputs.symbol, "no factual trades stream")
    total = state.taker_buy_volume + state.taker_sell_volume
    if total <= 0:
        return unavailable(spec_of("21_ORDER_FLOW_ML"), inputs.symbol, "zero taker volume")
    cvd_ratio = float(state.cvd) / float(total)
    imbalance = state.imbalance_l5
    close_values = closes(inputs.series("15m"))
    velocity = 0.0
    if len(close_values) >= 6 and close_values[-6] > 0:
        velocity = close_values[-1] / close_values[-6] - 1.0
    atr_values = ind.atr(highs(inputs.series("15m")), lows(inputs.series("15m")), close_values, 14)
    velocity_norm = (
        velocity / (atr_values[-1] / close_values[-1])
        if atr_values and close_values[-1] > 0
        else 0.0
    )
    logit = (1.6 * cvd_ratio) + (0.8 * float(imbalance)) + (0.5 * clamp(velocity_norm, -2.0, 2.0))
    probability_up = 1.0 / (1.0 + math.exp(-logit))
    score = (probability_up - 0.5) * 2.0
    return _evidence(
        "21_ORDER_FLOW_ML",
        inputs,
        score=score,
        confidence=min(0.8, 0.3 + min(1.0, state.trade_count / 100.0) * 0.3),
        theory="Logistic proxy over taker-flow, book imbalance and price velocity.",
        support=[f"P(up)={probability_up:.3f} cvd_ratio={cvd_ratio:.3f} imbalance={imbalance:.3f}"]
        if score > 0
        else [],
        counter=[f"P(up)={probability_up:.3f} cvd_ratio={cvd_ratio:.3f} imbalance={imbalance:.3f}"]
        if score < 0
        else [],
        neutral=[f"P(up)={probability_up:.3f}"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={
            "artifact_status": "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED",
            "probability_up": probability_up,
            "cvd_ratio": cvd_ratio,
            "imbalance_l5": float(imbalance),
            "velocity_norm": velocity_norm,
        },
        quality=EvidenceQuality.DEGRADED,
        entry_use="order-flow probability evidence (provisional)",
        exit_use="flow reversal probability evidence",
        reassessment_use="probability regime shift is a material flow event",
        invalidation="proxy unvalidated by Growth; must not be sole entry reason",
    )


# --------------------------------------------------------------------------- 22
def model_22_orderbook_imbalance(inputs: ExpertInputs) -> ModelEvidence:
    if inputs.state is None:
        return unavailable(
            spec_of("22_ORDERBOOK_IMBALANCE"), inputs.symbol, "no factual market state"
        )
    state = inputs.state
    if state.best_bid <= 0 or state.best_ask <= 0:
        return unavailable(spec_of("22_ORDERBOOK_IMBALANCE"), inputs.symbol, "no two-sided book")
    imbalance_l5 = float(state.imbalance_l5)
    mid = (state.best_bid + state.best_ask) / 2
    micro_tilt = float((state.microprice - mid) / mid) if mid > 0 and state.microprice > 0 else 0.0
    spread_penalty = 1.0
    spread_bps = float(state.spread_bps)
    if spread_bps > 25.0:
        spread_penalty = 0.5
    score = clamp((imbalance_l5 + micro_tilt * 200.0) * spread_penalty)
    return _evidence(
        "22_ORDERBOOK_IMBALANCE",
        inputs,
        score=score,
        confidence=min(0.85, (0.4 + 0.3 * min(1.0, abs(score))) * spread_penalty),
        theory="L1/L5/L10 book imbalance, microprice tilt and spread quality.",
        support=[
            f"imb5={imbalance_l5:.3f} tilt={micro_tilt:.6f} spread_bps={spread_bps:.2f}"
        ]
        if score > 0
        else [],
        counter=[
            f"imb5={imbalance_l5:.3f} tilt={micro_tilt:.6f} spread_bps={spread_bps:.2f}"
        ]
        if score < 0
        else [],
        neutral=[f"balanced book (imbalance={imbalance_l5:.3f})"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        metrics={
            "imbalance_l5": imbalance_l5,
            "imbalance": float(state.imbalance),
            "microprice": float(state.microprice),
            "spread_bps": spread_bps,
            "depth_bid_5": float(state.depth_bid_5),
            "depth_ask_5": float(state.depth_ask_5),
            "depth_bid_10": float(state.depth_bid_10),
            "depth_ask_10": float(state.depth_ask_10),
        },
        quality=EvidenceQuality.HEALTHY if spread_bps <= 25.0 else EvidenceQuality.DEGRADED,
        entry_use="microstructure entry timing",
        exit_use="book deterioration is Fast Profit / exit review evidence",
        reassessment_use="order-book dislocation is a material event (may bypass dedup)",
        invalidation="book imbalance normalizes/reverses",
    )


# --------------------------------------------------------------------------- 23
def model_23_funding_basis(inputs: ExpertInputs) -> ModelEvidence:
    if inputs.state is None:
        return unavailable(spec_of("23_FUNDING_BASIS"), inputs.symbol, "no factual market state")
    state = inputs.state
    if state.funding_rate is None and state.basis is None:
        return unavailable(spec_of("23_FUNDING_BASIS"), inputs.symbol, "no funding/basis facts")
    funding = float(state.funding_rate or 0.0)
    basis = float(state.basis or 0.0)
    score = clamp(-(funding / 0.001) * 0.5 - (basis / 0.002) * 0.5)
    notes = [f"funding={funding:.8f} basis={basis:.8f}"]
    if abs(score) < 0.15:
        notes = [f"funding/basis balanced ({notes[0]})"]
    return _evidence(
        "23_FUNDING_BASIS",
        inputs,
        score=score,
        confidence=0.4 + 0.25 * min(1.0, abs(score)),
        theory="Funding and basis measure leveraged crowding; extremes mean-revert.",
        support=notes if score > 0 else [],
        counter=notes if score < 0 else [],
        neutral=notes if direction_from_score(score) == EvidenceDirection.NEUTRAL else [],
        metrics={"funding_rate": funding, "basis": basis},
        entry_use="crowding context for entries",
        exit_use="funding/basis extreme against position supports exit review",
        reassessment_use="funding/basis anomaly is a material positioning event",
        invalidation="crowding normalizes without price reversal",
    )


# --------------------------------------------------------------------------- 24
def model_24_market_regime(inputs: ExpertInputs) -> ModelEvidence:
    timeframe = "1h"
    candles = inputs.series(timeframe)
    close_values = closes(candles)
    if len(close_values) < 60:
        return unavailable(
            spec_of("24_MARKET_REGIME"), inputs.symbol, "insufficient history for regime"
        )
    adx_values, plus, minus = ind.adx_di(highs(candles), lows(candles), close_values, 14)
    natr_values = ind.natr(highs(candles), lows(candles), close_values, 14)
    bands = ind.bollinger(close_values, 20, 2.0)
    atr_values = ind.atr(highs(candles), lows(candles), close_values, 14)
    if not natr_values or not atr_values:
        return unavailable(spec_of("24_MARKET_REGIME"), inputs.symbol, "regime inputs undefined")
    natr = natr_values[-1]
    natr_history = natr_values[-60:] if len(natr_values) >= 60 else natr_values
    natr_rank = sum(1 for value in natr_history if value <= natr) / len(natr_history)
    adx = adx_values[-1] if adx_values else 0.0
    direction = plus[-1] - minus[-1] if plus and minus else 0.0
    bandwidth_pct = 0.0
    bandwidth_expanding = False
    if bands:
        middle, upper, lower = bands[-1]
        bandwidth_pct = (upper - lower) / middle * 100.0 if middle > 0 else 0.0
        if len(bands) >= 6:
            prior = bands[-6][1] - bands[-6][2]
            bandwidth_expanding = (upper - lower) > prior
    large_activity = bool(inputs.state and inputs.state.large_trade_count >= 5)
    price_velocity = (
        abs(close_values[-1] / close_values[-2] - 1.0)
        if len(close_values) >= 2 and close_values[-2] > 0
        else 0.0
    )
    atr_pct = atr_values[-1] / close_values[-1] if close_values[-1] > 0 else 0.0
    if large_activity and price_velocity > max(3.0 * atr_pct, 0.01):
        regime = "LIQUIDATION_DISLOCATION"
    elif natr_rank > 0.9:
        regime = "HIGH_VOLATILITY"
    elif adx >= 25 and direction > 0:
        regime = "TREND_UP"
    elif adx >= 25 and direction < 0:
        regime = "TREND_DOWN"
    elif bandwidth_expanding and abs(price_velocity) > atr_pct:
        regime = "BREAKOUT_EXPANSION"
    elif adx < 20:
        regime = "RANGE"
    else:
        regime = "UNCERTAIN"
    return _evidence(
        "24_MARKET_REGIME",
        inputs,
        score=0.0,
        confidence=0.6 if regime != "UNCERTAIN" else 0.3,
        theory="Regime classifier over ADX, NATR rank, Bollinger bandwidth and activity.",
        neutral=[f"regime={regime} adx={adx:.2f} natr={natr:.3f} bandwidth={bandwidth_pct:.3f}%"],
        metrics={
            "regime": regime,
            "adx": adx,
            "di_spread": direction,
            "natr": natr,
            "natr_rank": natr_rank,
            "bandwidth_pct": bandwidth_pct,
            "bandwidth_expanding": bandwidth_expanding,
            "atr_pct": atr_pct,
            "price_velocity": price_velocity,
        },
        timeframes=("1h",),
        regime_compatibility=list(REGIME_LABELS),
    )


# --------------------------------------------------------------------------- 25
def model_25_meta_forecast(inputs: ExpertInputs, evidence: list[ModelEvidence]) -> ModelEvidence:
    available = [
        item for item in evidence if item.available and item.model_id != "25_META_FORECAST"
    ]
    if not available:
        return unavailable(
            spec_of("25_META_FORECAST"), inputs.symbol, "no available model evidence to combine"
        )
    weighted_sum = 0.0
    weight_total = 0.0
    factor_scores: dict[str, float] = {}
    for item in available:
        weight = max(0.05, item.confidence)
        weighted_sum += item.direction_score * weight
        weight_total += weight
        factor_scores[item.model_id] = item.direction_score
    combined = weighted_sum / weight_total if weight_total > 0 else 0.0
    # Expected move proxy: 4x the 15m ATR percent (short horizon), conservatively
    # compared against the unified all-in cost estimate.
    close_values = closes(inputs.series("15m"))
    _, high_values, low_values, _, _ = _ohlcv(inputs, "15m")
    atr_values = ind.atr(high_values, low_values, close_values, 14)
    atr_pct = atr_values[-1] / close_values[-1] if atr_values and close_values[-1] > 0 else 0.0
    expected_move_bps = atr_pct * 4.0 * 10_000.0
    cost_bps = inputs.costs.total_cost_bps
    edge_ratio = expected_move_bps / cost_bps if cost_bps > 0 else 0.0
    probability_up = 1.0 / (1.0 + math.exp(-combined * 2.0))
    edge_factor = clamp((edge_ratio - 1.0) / 2.0, 0.0, 1.0)
    score = (probability_up - 0.5) * 2.0 * edge_factor
    counter: list[str] = []
    if edge_ratio <= 1.0:
        counter.append(
            f"EXPECTED_EDGE_BELOW_ALL_IN_COST expected={expected_move_bps:.1f}bps "
            f"cost={cost_bps:.1f}bps"
        )
    disagreement = sum(1 for item in available if item.direction == EvidenceDirection.SHORT)
    if disagreement:
        counter.append(
            f"{disagreement} of {len(available)} available models oppose the combined direction"
        )
    return _evidence(
        "25_META_FORECAST",
        inputs,
        score=score,
        confidence=min(0.7, 0.25 + 0.4 * abs(score)) if edge_ratio > 1.0 else 0.2,
        theory="Restrained meta forecast combining available models against all-in cost.",
        counter=counter,
        neutral=[f"p_up={probability_up:.3f} combined={combined:.3f}"]
        if direction_from_score(score) == EvidenceDirection.NEUTRAL
        else [],
        support=[f"p_up={probability_up:.3f} edge_ratio={edge_ratio:.2f}"] if score > 0 else [],
        metrics={
            "artifact_status": "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED",
            "probability_up": probability_up,
            "combined_score": combined,
            "expected_move_bps": expected_move_bps,
            "all_in_cost_bps": cost_bps,
            "edge_ratio": edge_ratio,
            "models_combined": len(available),
            "factor_scores": factor_scores,
        },
        quality=EvidenceQuality.DEGRADED,
        entry_use="meta probability gate input (provisional)",
        exit_use="meta probability deterioration evidence",
        reassessment_use="meta probability shift is a material aggregate event",
        invalidation="all-in cost exceeds expected edge",
    )


# Registry of the directional/context models evaluated before the meta model.
MODEL_FUNCTIONS = {
    "01_EMA_MULTI_TF": model_01_ema_multi_tf,
    "02_MACD": model_02_macd,
    "03_ADX_DI": model_03_adx_di,
    "04_RSI_CONTEXT": model_04_rsi_context,
    "05_BOLLINGER_REGIME": model_05_bollinger_regime,
    "06_VWAP_DEVIATION": model_06_vwap_deviation,
    "07_ATR_NATR": model_07_atr_natr,
    "08_VOLUME_BREAKOUT": model_08_volume_breakout,
    "09_CVD_TAKER_FLOW": model_09_cvd_taker_flow,
    "10_PRICE_OI": model_10_price_oi,
    "11_SMA_STRUCTURE": model_11_sma_structure,
    "12_SUPERTREND": model_12_supertrend,
    "13_STOCH_RSI": model_13_stoch_rsi,
    "14_ROC": model_14_roc,
    "15_CCI": model_15_cci,
    "16_PRICE_ZSCORE": model_16_price_zscore,
    "17_SUPPORT_RESISTANCE": model_17_support_resistance,
    "18_OBV": model_18_obv,
    "19_MFI": model_19_mfi,
    "20_CMF": model_20_cmf,
    "21_ORDER_FLOW_ML": model_21_order_flow_ml,
    "22_ORDERBOOK_IMBALANCE": model_22_orderbook_imbalance,
    "23_FUNDING_BASIS": model_23_funding_basis,
    "24_MARKET_REGIME": model_24_market_regime,
}


def evaluate_all(inputs: ExpertInputs) -> dict[str, ModelEvidence]:
    """Evaluate models 01..24 (+25 meta last) exactly once. Evidence only."""
    outputs: dict[str, ModelEvidence] = {}
    regime = model_24_market_regime(inputs)
    outputs[regime.model_id] = regime
    if regime.available:
        inputs.extra["regime"] = str(regime.metrics.get("regime", "UNCERTAIN"))
    for model_id, function in MODEL_FUNCTIONS.items():
        if model_id == "24_MARKET_REGIME":
            continue
        outputs[model_id] = function(inputs)
    ordered = [outputs[spec.model_id] for spec in REQUIRED_MODELS if spec.model_id in outputs]
    meta = model_25_meta_forecast(inputs, ordered)
    outputs[meta.model_id] = meta
    return {spec.model_id: outputs[spec.model_id] for spec in REQUIRED_MODELS}
