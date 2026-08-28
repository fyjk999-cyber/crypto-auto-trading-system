"""Advisory technical indicators computed from real OHLCV candles.

The output is evidence for the Chief Trader. It never returns a trade decision
or a hard gate. Indicators that lack enough real history stay ``None``.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


def _series(candles: Sequence[dict], key: str) -> list[float]:
    values: list[float] = []
    for candle in candles:
        try:
            value = float(candle[key])
        except (KeyError, TypeError, ValueError):
            return []
        if not math.isfinite(value):
            return []
        values.append(value)
    return values


def _sma(values: Sequence[float], period: int) -> float | None:
    return sum(values[-period:]) / period if len(values) >= period else None


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    result = [current]
    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)
    return result


def _ema(values: Sequence[float], period: int) -> float | None:
    result = _ema_series(values, period)
    return result[-1] if result else None


def _rsi(values: Sequence[float], period: int) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    window = changes[-period:]
    gain = sum(max(change, 0.0) for change in window) / period
    loss = sum(max(-change, 0.0) for change in window) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    relative_strength = gain / loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _true_ranges(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
) -> list[float]:
    if not high or len(high) != len(low) or len(high) != len(close):
        return []
    result = [high[0] - low[0]]
    for index in range(1, len(close)):
        result.append(
            max(
                high[index] - low[index],
                abs(high[index] - close[index - 1]),
                abs(low[index] - close[index - 1]),
            )
        )
    return result


def _atr(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> float | None:
    return _sma(_true_ranges(high, low, close), period)


def _macd(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    fast = _ema_series(values, 12)
    slow = _ema_series(values, 26)
    if not slow:
        return None, None, None
    aligned_fast = fast[-len(slow) :]
    lines = [a - b for a, b in zip(aligned_fast, slow, strict=False)]
    signal_series = _ema_series(lines, 9)
    line = lines[-1]
    if not signal_series:
        return line, None, None
    signal = signal_series[-1]
    return line, signal, line - signal


def _stochastic(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> tuple[float | None, float | None]:
    if len(close) < period:
        return None, None
    k_values: list[float] = []
    first_end = max(period - 1, len(close) - 3)
    for end in range(first_end, len(close)):
        start = end - period + 1
        highest = max(high[start : end + 1])
        lowest = min(low[start : end + 1])
        if highest == lowest:
            k_values.append(50.0)
        else:
            k_values.append(100.0 * (close[end] - lowest) / (highest - lowest))
    return k_values[-1], _sma(k_values, 3)


def _adx(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> tuple[float | None, float | None, float | None]:
    if len(close) < period + 1:
        return None, None, None
    true_ranges = _true_ranges(high, low, close)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for index in range(1, len(close)):
        up = high[index] - high[index - 1]
        down = low[index - 1] - low[index]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    dx_values: list[float] = []
    last_plus = last_minus = None
    for end in range(period - 1, len(close)):
        start = end - period + 1
        tr_sum = sum(true_ranges[start : end + 1])
        if tr_sum <= 0:
            continue
        last_plus = 100.0 * sum(plus_dm[start : end + 1]) / tr_sum
        last_minus = 100.0 * sum(minus_dm[start : end + 1]) / tr_sum
        denominator = last_plus + last_minus
        dx_values.append(
            0.0
            if denominator == 0
            else 100.0 * abs(last_plus - last_minus) / denominator
        )
    return _sma(dx_values, period), last_plus, last_minus


def _obv(close: Sequence[float], volume: Sequence[float]) -> float | None:
    if not close or len(close) != len(volume):
        return None
    result = 0.0
    for index in range(1, len(close)):
        if close[index] > close[index - 1]:
            result += volume[index]
        elif close[index] < close[index - 1]:
            result -= volume[index]
    return result


def _mfi(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    period: int = 14,
) -> float | None:
    if len(close) < period + 1:
        return None
    typical = [
        (high_value + low_value + close_value) / 3.0
        for high_value, low_value, close_value in zip(high, low, close, strict=False)
    ]
    positive = negative = 0.0
    for index in range(len(close) - period, len(close)):
        flow = typical[index] * volume[index]
        if typical[index] > typical[index - 1]:
            positive += flow
        elif typical[index] < typical[index - 1]:
            negative += flow
    if negative == 0:
        return 100.0 if positive > 0 else 50.0
    ratio = positive / negative
    return 100.0 - 100.0 / (1.0 + ratio)


def _cci(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 20,
) -> float | None:
    if len(close) < period:
        return None
    typical = [
        (high_value + low_value + close_value) / 3.0
        for high_value, low_value, close_value in zip(
            high[-period:], low[-period:], close[-period:], strict=False
        )
    ]
    mean = sum(typical) / period
    deviation = sum(abs(value - mean) for value in typical) / period
    return 0.0 if deviation == 0 else (typical[-1] - mean) / (0.015 * deviation)


def _vwap(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    period: int = 20,
) -> float | None:
    if len(close) < period:
        return None
    total_volume = sum(volume[-period:])
    if total_volume <= 0:
        return None
    start = len(close) - period
    weighted = sum(
        ((high[index] + low[index] + close[index]) / 3.0) * volume[index]
        for index in range(start, len(close))
    )
    return weighted / total_volume


def _ichimoku(high: Sequence[float], low: Sequence[float]) -> dict[str, float | None]:
    def midpoint(period: int) -> float | None:
        if len(high) < period:
            return None
        return (max(high[-period:]) + min(low[-period:])) / 2.0

    tenkan = midpoint(9)
    kijun = midpoint(26)
    span_b = midpoint(52)
    span_a = None
    if tenkan is not None and kijun is not None:
        span_a = (tenkan + kijun) / 2.0
    return {
        "tenkan_9": tenkan,
        "kijun_26": kijun,
        "senkou_a": span_a,
        "senkou_b_52": span_b,
    }


def calculate_technical_indicators(candles: Sequence[dict]) -> dict:
    """Return a compact JSON-safe snapshot with advisory authority only."""
    close = _series(candles, "close")
    high = _series(candles, "high")
    low = _series(candles, "low")
    volume = _series(candles, "volume")
    valid = close and high and low and volume
    same_length = len(close) == len(high) == len(low) == len(volume)
    if not valid or not same_length:
        return {
            "authority": "ADVISORY",
            "status": "UNAVAILABLE",
            "sample_count": 0,
            "indicators": {},
        }

    price = close[-1]
    atr14 = _atr(high, low, close)
    macd_line, macd_signal, macd_histogram = _macd(close)
    stochastic_k, stochastic_d = _stochastic(high, low, close)
    adx14, plus_di14, minus_di14 = _adx(high, low, close)
    bb_mid = _sma(close, 20)
    bb_std = statistics.pstdev(close[-20:]) if len(close) >= 20 else None
    bb_upper = bb_mid + 2 * bb_std if bb_mid is not None and bb_std is not None else None
    bb_lower = bb_mid - 2 * bb_std if bb_mid is not None and bb_std is not None else None
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)
    donchian20_high = max(high[-20:]) if len(high) >= 20 else None
    donchian20_low = min(low[-20:]) if len(low) >= 20 else None
    donchian50_high = max(high[-50:]) if len(high) >= 50 else None
    donchian50_low = min(low[-50:]) if len(low) >= 50 else None
    returns = [
        close[index] / close[index - 1] - 1.0
        for index in range(1, len(close))
        if close[index - 1] != 0
    ]
    realized_volatility20 = (
        statistics.pstdev(returns[-20:]) if len(returns) >= 20 else None
    )
    z_mid = _sma(close, 20)
    z_std = statistics.pstdev(close[-20:]) if len(close) >= 20 else None
    zscore20 = None
    if z_mid is not None and z_std not in (None, 0):
        zscore20 = (price - z_mid) / z_std
    volume_baseline = _sma(volume, 20)
    volume_ratio20 = None
    if volume_baseline is not None and volume_baseline > 0:
        volume_ratio20 = volume[-1] / volume_baseline
    williams_r14 = None
    if len(close) >= 14:
        highest = max(high[-14:])
        lowest = min(low[-14:])
        williams_r14 = (
            -50.0
            if highest == lowest
            else -100.0 * (highest - price) / (highest - lowest)
        )
    roc12 = None
    if len(close) >= 13 and close[-13] != 0:
        roc12 = price / close[-13] - 1.0
    momentum10 = price - close[-11] if len(close) >= 11 else None
    vwap20 = _vwap(high, low, close, volume)
    keltner_upper = None
    keltner_lower = None
    if ema20 is not None and atr14 is not None:
        keltner_upper = ema20 + 2 * atr14
        keltner_lower = ema20 - 2 * atr14
    bollinger_bandwidth = None
    bollinger_percent_b = None
    if bb_upper is not None and bb_lower is not None:
        if bb_mid not in (None, 0):
            bollinger_bandwidth = (bb_upper - bb_lower) / bb_mid
        if bb_upper != bb_lower:
            bollinger_percent_b = (price - bb_lower) / (bb_upper - bb_lower)

    indicators = {
        **{f"sma_{period}": _sma(close, period) for period in (5, 10, 20, 50, 100, 200)},
        **{
            f"ema_{period}": _ema(close, period)
            for period in (5, 9, 12, 20, 21, 26, 50, 100, 200)
        },
        "rsi_6": _rsi(close, 6),
        "rsi_14": _rsi(close, 14),
        "rsi_21": _rsi(close, 21),
        "macd_12_26": macd_line,
        "macd_signal_9": macd_signal,
        "macd_histogram": macd_histogram,
        "bollinger_mid_20": bb_mid,
        "bollinger_upper_20_2": bb_upper,
        "bollinger_lower_20_2": bb_lower,
        "bollinger_bandwidth": bollinger_bandwidth,
        "bollinger_percent_b": bollinger_percent_b,
        "atr_14": atr14,
        "atr_percent_14": atr14 / price if atr14 is not None and price else None,
        "adx_14": adx14,
        "plus_di_14": plus_di14,
        "minus_di_14": minus_di14,
        "stochastic_k_14": stochastic_k,
        "stochastic_d_3": stochastic_d,
        "williams_r_14": williams_r14,
        "cci_20": _cci(high, low, close),
        "roc_12": roc12,
        "momentum_10": momentum10,
        "obv": _obv(close, volume),
        "mfi_14": _mfi(high, low, close, volume),
        "vwap_20": vwap20,
        "donchian_high_20": donchian20_high,
        "donchian_low_20": donchian20_low,
        "donchian_high_50": donchian50_high,
        "donchian_low_50": donchian50_low,
        "keltner_mid_20": ema20,
        "keltner_upper_20": keltner_upper,
        "keltner_lower_20": keltner_lower,
        "realized_volatility_20": realized_volatility20,
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
