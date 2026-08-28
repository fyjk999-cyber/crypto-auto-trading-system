"""Technical-indicator evidence computed from real OHLCV candles.

This module is deliberately advisory. It measures market state for the Chief
Trader but never returns a trade decision or a hard gate. Missing history is
represented by ``None`` rather than fabricated values.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


def _values(candles: Sequence[dict], key: str) -> list[float]:
    result: list[float] = []
    for candle in candles:
        try:
            value = float(candle[key])
        except (KeyError, TypeError, ValueError):
            return []
        if not math.isfinite(value):
            return []
        result.append(value)
    return result


def _sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    result = [ema]
    for value in values[period:]:
        ema = alpha * value + (1.0 - alpha) * ema
        result.append(ema)
    return result


def _ema(values: Sequence[float], period: int) -> float | None:
    series = _ema_series(values, period)
    return series[-1] if series else None


def _rsi(values: Sequence[float], period: int) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    window = changes[-period:]
    gains = sum(max(change, 0.0) for change in window) / period
    losses = sum(max(-change, 0.0) for change in window) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def _true_ranges(high: Sequence[float], low: Sequence[float], close: Sequence[float]) -> list[float]:
    if not high or len(high) != len(low) or len(high) != len(close):
        return []
    result = [high[0] - low[0]]
    for i in range(1, len(close)):
        result.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return result


def _atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14) -> float | None:
    tr = _true_ranges(high, low, close)
    return _sma(tr, period)


def _rolling_std(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return statistics.pstdev(values[-period:])


def _macd(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    fast = _ema_series(values, 12)
    slow = _ema_series(values, 26)
    if not slow:
        return None, None, None
    # Align the fast EMA to the timestamps where the slow EMA exists.
    fast_aligned = fast[-len(slow):]
    line_series = [a - b for a, b in zip(fast_aligned, slow, strict=False)]
    signal_series = _ema_series(line_series, 9)
    line = line_series[-1]
    if not signal_series:
        return line, None, None
    signal = signal_series[-1]
    return line, signal, line - signal


def _stochastic(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14) -> tuple[float | None, float | None]:
    if len(close) < period:
        return None, None
    ks: list[float] = []
    for end in range(max(period - 1, len(close) - 3), len(close)):
        start = end - period + 1
        hh = max(high[start : end + 1])
        ll = min(low[start : end + 1])
        ks.append(50.0 if hh == ll else 100.0 * (close[end] - ll) / (hh - ll))
    return ks[-1], _sma(ks, 3)


def _adx(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14) -> tuple[float | None, float | None, float | None]:
    if len(close) < period + 1:
        return None, None, None
    tr = _true_ranges(high, low, close)
    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    for i in range(1, len(close)):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    dx: list[float] = []
    last_plus = last_minus = None
    for end in range(period - 1, len(close)):
        start = end - period + 1
        tr_sum = sum(tr[start : end + 1])
        if tr_sum <= 0:
            continue
        plus_di = 100.0 * sum(plus_dm[start : end + 1]) / tr_sum
        minus_di = 100.0 * sum(minus_dm[start : end + 1]) / tr_sum
        denom = plus_di + minus_di
        dx.append(0.0 if denom == 0 else 100.0 * abs(plus_di - minus_di) / denom)
        last_plus, last_minus = plus_di, minus_di
    return _sma(dx, period), last_plus, last_minus


def _obv(close: Sequence[float], volume: Sequence[float]) -> float | None:
    if not close or len(close) != len(volume):
        return None
    value = 0.0
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            value += volume[i]
        elif close[i] < close[i - 1]:
            value -= volume[i]
    return value


def _mfi(high: Sequence[float], low: Sequence[float], close: Sequence[float], volume: Sequence[float], period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    typical = [(h + l + c) / 3.0 for h, l, c in zip(high, low, close, strict=False)]
    positive = negative = 0.0
    for i in range(len(close) - period, len(close)):
        flow = typical[i] * volume[i]
        if typical[i] > typical[i - 1]:
            positive += flow
        elif typical[i] < typical[i - 1]:
            negative += flow
    if negative == 0:
        return 100.0 if positive > 0 else 50.0
    ratio = positive / negative
    return 100.0 - 100.0 / (1.0 + ratio)


def _cci(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 20) -> float | None:
    if len(close) < period:
        return None
    typical = [(h + l + c) / 3.0 for h, l, c in zip(high[-period:], low[-period:], close[-period:], strict=False)]
    mean = sum(typical) / period
    deviation = sum(abs(value - mean) for value in typical) / period
    return 0.0 if deviation == 0 else (typical[-1] - mean) / (0.015 * deviation)


def _vwap(high: Sequence[float], low: Sequence[float], close: Sequence[float], volume: Sequence[float], period: int = 20) -> float | None:
    if len(close) < period:
        return None
    total_volume = sum(volume[-period:])
    if total_volume <= 0:
        return None
    weighted = sum(((high[i] + low[i] + close[i]) / 3.0) * volume[i] for i in range(len(close) - period, len(close)))
    return weighted / total_volume


def _ichimoku(high: Sequence[float], low: Sequence[float]) -> dict[str, float | None]:
    def midpoint(period: int) -> float | None:
        if len(high) < period:
            return None
        return (max(high[-period:]) + min(low[-period:])) / 2.0

    tenkan = midpoint(9)
    kijun = midpoint(26)
    span_b = midpoint(52)
    span_a = (tenkan + kijun) / 2.0 if tenkan is not None and kijun is not None else None
    return {"tenkan_9": tenkan, "kijun_26": kijun, "senkou_a": span_a, "senkou_b_52": span_b}


def calculate_technical_indicators(candles: Sequence[dict]) -> dict:
    """Return a compact, JSON-safe advisory indicator snapshot."""
    close = _values(candles, "close")
    high = _values(candles, "high")
    low = _values(candles, "low")
    volume = _values(candles, "volume")
    if not close or not high or not low or not volume or not (len(close) == len(high) == len(low) == len(volume)):
        return {"authority": "ADVISORY", "status": "UNAVAILABLE", "sample_count": 0, "indicators": {}}

    price = close[-1]
    atr14 = _atr(high, low, close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    stoch_k, stoch_d = _stochastic(high, low, close)
    adx14, plus_di14, minus_di14 = _adx(high, low, close)
    bb_mid = _sma(close, 20)
    bb_std = _rolling_std(close, 20)
    bb_upper = bb_mid + 2 * bb_std if bb_mid is not None and bb_std is not None else None
    bb_lower = bb_mid - 2 * bb_std if bb_mid is not None and bb_std is not None else None
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)
    donchian20_high = max(high[-20:]) if len(high) >= 20 else None
    donchian20_low = min(low[-20:]) if len(low) >= 20 else None
    donchian50_high = max(high[-50:]) if len(high) >= 50 else None
    donchian50_low = min(low[-50:]) if len(low) >= 50 else None
    returns = [(close[i] / close[i - 1] - 1.0) for i in range(1, len(close)) if close[i - 1] != 0]
    rv20 = statistics.pstdev(returns[-20:]) if len(returns) >= 20 else None
    z20_mid = _sma(close, 20)
    z20_std = _rolling_std(close, 20)
    zscore20 = (price - z20_mid) / z20_std if z20_mid is not None and z20_std not in (None, 0) else None
    vol_baseline = _sma(volume, 20)
    volume_ratio20 = volume[-1] / vol_baseline if vol_baseline and vol_baseline > 0 else None
    williams_r14 = None
    if len(close) >= 14:
        hh, ll = max(high[-14:]), min(low[-14:])
        williams_r14 = -50.0 if hh == ll else -100.0 * (hh - price) / (hh - ll)
    roc12 = (price / close[-13] - 1.0) if len(close) >= 13 and close[-13] != 0 else None
    momentum10 = price - close[-11] if len(close) >= 11 else None
    vwap20 = _vwap(high, low, close, volume, 20)
    keltner_upper = ema20 + 2 * atr14 if ema20 is not None and atr14 is not None else None
    keltner_lower = ema20 - 2 * atr14 if ema20 is not None and atr14 is not None else None

    indicators = {
        **{f"sma_{p}": _sma(close, p) for p in (5, 10, 20, 50, 100, 200)},
        **{f"ema_{p}": _ema(close, p) for p in (5, 9, 12, 20, 21, 26, 50, 100, 200)},
        "rsi_6": _rsi(close, 6),
        "rsi_14": _rsi(close, 14),
        "rsi_21": _rsi(close, 21),
        "macd_12_26": macd_line,
        "macd_signal_9": macd_signal,
        "macd_histogram": macd_hist,
        "bollinger_mid_20": bb_mid,
        "bollinger_upper_20_2": bb_upper,
        "bollinger_lower_20_2": bb_lower,
        "bollinger_bandwidth": (bb_upper - bb_lower) / bb_mid if bb_upper is not None and bb_lower is not None and bb_mid not in (None, 0) else None,
        "bollinger_percent_b": (price - bb_lower) / (bb_upper - bb_lower) if bb_upper is not None and bb_lower is not None and bb_upper != bb_lower else None,
        "atr_14": atr14,
        "atr_percent_14": atr14 / price if atr14 is not None and price else None,
        "adx_14": adx14,
        "plus_di_14": plus_di14,
        "minus_di_14": minus_di14,
        "stochastic_k_14": stoch_k,
        "stochastic_d_3": stoch_d,
        "williams_r_14": williams_r14,
        "cci_20": _cci(high, low, close, 20),
        "roc_12": roc12,
        "momentum_10": momentum10,
        "obv": _obv(close, volume),
        "mfi_14": _mfi(high, low, close, volume, 14),
        "vwap_20": vwap20,
        "donchian_high_20": donchian20_high,
        "donchian_low_20": donchian20_low,
        "donchian_high_50": donchian50_high,
        "donchian_low_50": donchian50_low,
        "keltner_mid_20": ema20,
        "keltner_upper_20": keltner_upper,
        "keltner_lower_20": keltner_lower,
        "realized_volatility_20": rv20,
        "zscore_20": zscore20,
        "volume_ratio_20": volume_ratio20,
        "price_vs_ema20": price / ema20 - 1.0 if ema20 else None,
        "price_vs_ema50": price / ema50 - 1.0 if ema50 else None,
        "price_vs_ema200": price / ema200 - 1.0 if ema200 else None,
        "recent_support_20": donchian20_low,
        "recent_resistance_20": donchian20_high,
        **_ichimoku(high, low),
    }
    available = sum(value is not None for value in indicators.values())
    return {
        "authority": "ADVISORY",
        "status": "OK" if available else "INSUFFICIENT_HISTORY",
        "sample_count": len(close),
        "price": price,
        "available_indicator_count": available,
        "indicators": indicators,
    }
