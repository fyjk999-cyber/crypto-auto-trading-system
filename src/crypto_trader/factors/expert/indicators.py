"""Pure-Python indicator math for the 25-model expert layer.

No third-party numerical dependency is introduced: the PAPER runtime keeps its
existing dependency footprint. All functions are deterministic and return
``None``/empty when the input history is insufficient — callers must surface
that as ``UNAVAILABLE`` instead of substituting a value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def sma(values: Sequence[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period:
        return []
    out: list[float] = []
    window_sum = sum(values[:period])
    out.append(window_sum / period)
    for index in range(period, len(values)):
        window_sum += values[index] - values[index - period]
        out.append(window_sum / period)
    return out


def ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period:
        return []
    multiplier = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for value in values[period:]:
        out.append((value - out[-1]) * multiplier + out[-1])
    return out


def true_ranges(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    out: list[float] = []
    for index in range(1, len(closes)):
        out.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[float]:
    tr = true_ranges(highs, lows, closes)
    if len(tr) < period:
        return []
    out = [sum(tr[:period]) / period]
    for value in tr[period:]:
        out.append((out[-1] * (period - 1) + value) / period)
    return out


def natr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[float]:
    values = atr(highs, lows, closes, period)
    if not values:
        return []
    closes_tail = list(closes)[period:]
    out: list[float] = []
    for index, value in enumerate(values):
        close = closes_tail[index] if index < len(closes_tail) else closes[-1]
        out.append(value / close * 100.0 if close > 0 else 0.0)
    return out


def rsi(values: Sequence[float], period: int = 14) -> list[float]:
    if len(values) < period + 1:
        return []
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        rs = gain / loss
        return 100.0 - 100.0 / (1.0 + rs)

    out = [_value(avg_gain, avg_loss)]
    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        out.append(_value(avg_gain, avg_loss))
    return out


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    if not fast_ema or not slow_ema:
        return [], [], []
    offset = slow - fast
    line = [fast_ema[index + offset] - slow_ema[index] for index in range(len(slow_ema))]
    signal_line = ema(line, signal)
    if not signal_line:
        return line, [], []
    offset_signal = len(line) - len(signal_line)
    histogram = [
        line[index + offset_signal] - signal_line[index] for index in range(len(signal_line))
    ]
    return line, signal_line, histogram


def adx_di(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> tuple[list[float], list[float], list[float]]:
    """Return (adx, plus_di, minus_di) Wilder-smoothed."""
    if len(closes) < period + 2:
        return [], [], []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for index in range(1, len(closes)):
        up_move = highs[index] - highs[index - 1]
        down_move = lows[index - 1] - lows[index]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        trs.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )

    def _wilder(values: list[float]) -> list[float]:
        smoothed = [sum(values[:period])]
        for value in values[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + value)
        return smoothed

    tr_s = _wilder(trs)
    plus_s = _wilder(plus_dm)
    minus_s = _wilder(minus_dm)
    plus_di: list[float] = []
    minus_di: list[float] = []
    dx: list[float] = []
    for index in range(len(tr_s)):
        if tr_s[index] <= 0:
            plus_di.append(0.0)
            minus_di.append(0.0)
            dx.append(0.0)
            continue
        plus = 100.0 * plus_s[index] / tr_s[index]
        minus = 100.0 * minus_s[index] / tr_s[index]
        plus_di.append(plus)
        minus_di.append(minus)
        total = plus + minus
        dx.append(100.0 * abs(plus - minus) / total if total > 0 else 0.0)
    if len(dx) < period:
        return [], [], []
    adx = [sum(dx[:period]) / period]
    for value in dx[period:]:
        adx.append((adx[-1] * (period - 1) + value) / period)
    trim = len(adx)
    return adx, plus_di[-trim:], minus_di[-trim:]


def bollinger(
    values: Sequence[float], period: int = 20, deviations: float = 2.0
) -> list[tuple[float, float, float]]:
    """Return (middle, upper, lower) per bar."""
    if len(values) < period:
        return []
    out: list[tuple[float, float, float]] = []
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        std = variance**0.5
        out.append((mean, mean + deviations * std, mean - deviations * std))
    return out


def stochastic_rsi(
    values: Sequence[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[list[float], list[float]]:
    rsi_values = rsi(values, rsi_period)
    if len(rsi_values) < stoch_period:
        return [], []
    raw_k: list[float] = []
    for index in range(stoch_period - 1, len(rsi_values)):
        window = rsi_values[index - stoch_period + 1 : index + 1]
        low, high = min(window), max(window)
        raw_k.append((rsi_values[index] - low) / (high - low) * 100.0 if high > low else 50.0)
    k_line = sma(raw_k, k_smooth)
    if not k_line:
        return [], []
    d_line = sma(k_line, d_smooth)
    return k_line, d_line


def roc(values: Sequence[float], period: int = 12) -> list[float]:
    if len(values) <= period:
        return []
    return [
        (values[index] - values[index - period]) / values[index - period] * 100.0
        if values[index - period] > 0
        else 0.0
        for index in range(period, len(values))
    ]


def cci(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 20
) -> list[float]:
    if len(closes) < period:
        return []
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    out: list[float] = []
    for index in range(period - 1, len(typical)):
        window = typical[index - period + 1 : index + 1]
        mean = sum(window) / period
        deviation = sum(abs(value - mean) for value in window) / period
        out.append((typical[index] - mean) / (0.015 * deviation) if deviation > 0 else 0.0)
    return out


def zscore(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = list(values)[-period:]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    if variance <= 0:
        return None
    return (window[-1] - mean) / variance**0.5


def supertrend(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> list[tuple[float, int]]:
    """Return (line, trend) with trend=1 up / -1 down."""
    atr_values = atr(highs, lows, closes, period)
    if not atr_values:
        return []
    offset = len(closes) - len(atr_values)
    final_upper = 0.0
    final_lower = 0.0
    trend = 1
    out: list[tuple[float, int]] = []
    for index, atr_value in enumerate(atr_values):
        bar = index + offset
        mid = (highs[bar] + lows[bar]) / 2.0
        upper = mid + multiplier * atr_value
        lower = mid - multiplier * atr_value
        previous_close = closes[bar - 1] if bar > 0 else closes[bar]
        if index == 0:
            final_upper, final_lower = upper, lower
        else:
            final_upper = (
                upper if upper < final_upper or previous_close > final_upper else final_upper
            )
            final_lower = (
                lower if lower > final_lower or previous_close < final_lower else final_lower
            )
        if trend == 1 and closes[bar] < final_lower:
            trend = -1
        elif trend == -1 and closes[bar] > final_upper:
            trend = 1
        out.append((final_lower if trend == 1 else final_upper, trend))
    return out


def obv(closes: Sequence[float], volumes: Sequence[float]) -> list[float]:
    if len(closes) != len(volumes) or not closes:
        return []
    out = [0.0]
    for index in range(1, len(closes)):
        if closes[index] > closes[index - 1]:
            out.append(out[-1] + volumes[index])
        elif closes[index] < closes[index - 1]:
            out.append(out[-1] - volumes[index])
        else:
            out.append(out[-1])
    return out


def mfi(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    period: int = 14,
) -> list[float]:
    if len(closes) < period + 1:
        return []
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    positive: list[float] = []
    negative: list[float] = []
    for index in range(1, len(typical)):
        flow = typical[index] * volumes[index]
        if typical[index] > typical[index - 1]:
            positive.append(flow)
            negative.append(0.0)
        else:
            positive.append(0.0)
            negative.append(flow)
    out: list[float] = []
    for index in range(period - 1, len(positive)):
        pos = sum(positive[index - period + 1 : index + 1])
        neg = sum(negative[index - period + 1 : index + 1])
        out.append(100.0 - 100.0 / (1.0 + pos / neg) if neg > 0 else 100.0)
    return out


def cmf(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    period: int = 20,
) -> list[float]:
    if len(closes) < period:
        return []
    mfv: list[float] = []
    for index in range(len(closes)):
        span = highs[index] - lows[index]
        ratio = (
            ((closes[index] - lows[index]) - (highs[index] - closes[index])) / span
            if span > 0
            else 0.0
        )
        mfv.append(ratio * volumes[index])
    out: list[float] = []
    for index in range(period - 1, len(closes)):
        volume_sum = sum(volumes[index - period + 1 : index + 1])
        out.append(sum(mfv[index - period + 1 : index + 1]) / volume_sum if volume_sum > 0 else 0.0)
    return out


@dataclass(slots=True)
class SwingLevels:
    support: float | None
    resistance: float | None
    nearest_support_distance_pct: float | None
    nearest_resistance_distance_pct: float | None


def swing_levels(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], lookback: int = 20
) -> SwingLevels:
    if len(closes) < lookback or closes[-1] <= 0:
        return SwingLevels(None, None, None, None)
    window_highs = list(highs)[-lookback:]
    window_lows = list(lows)[-lookback:]
    price = closes[-1]
    prior_highs = window_highs[:-1]
    prior_lows = window_lows[:-1]
    resistance = max(prior_highs) if prior_highs else None
    support = min(prior_lows) if prior_lows else None
    return SwingLevels(
        support=support,
        resistance=resistance,
        nearest_support_distance_pct=((price - support) / price * 100.0) if support else None,
        nearest_resistance_distance_pct=((resistance - price) / price * 100.0)
        if resistance
        else None,
    )


def volume_profile_levels(
    closes: Sequence[float], volumes: Sequence[float], bins: int = 12
) -> tuple[float | None, float | None]:
    """Return (high-volume node, low-volume node) price levels."""
    if len(closes) < bins * 2 or len(closes) != len(volumes):
        return None, None
    low, high = min(closes), max(closes)
    if high <= low:
        return None, None
    width = (high - low) / bins
    histogram = [0.0] * bins
    for price, volume in zip(closes, volumes, strict=False):
        index = min(bins - 1, int((price - low) / width))
        histogram[index] += volume
    hvn_index = max(range(bins), key=lambda i: histogram[i])
    lvn_index = min(range(bins), key=lambda i: histogram[i])
    return low + (hvn_index + 0.5) * width, low + (lvn_index + 0.5) * width


def linear_slope(values: Sequence[float], period: int = 10) -> float | None:
    if len(values) < period:
        return None
    window = list(values)[-period:]
    n = len(window)
    mean_x = (n - 1) / 2.0
    mean_y = sum(window) / n
    denominator = sum((x - mean_x) ** 2 for x in range(n))
    if denominator <= 0:
        return None
    numerator = sum((x - mean_x) * (window[x] - mean_y) for x in range(n))
    return numerator / denominator


def pct_change(values: Sequence[float], period: int) -> float | None:
    if len(values) <= period or values[-period - 1] <= 0:
        return None
    return (values[-1] - values[-period - 1]) / values[-period - 1]


def realized_volatility(values: Sequence[float], period: int = 20) -> float | None:
    if len(values) < period + 1:
        return None
    returns = [
        values[i] / values[i - 1] - 1.0
        for i in range(len(values) - period, len(values))
        if values[i - 1] > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return variance**0.5
