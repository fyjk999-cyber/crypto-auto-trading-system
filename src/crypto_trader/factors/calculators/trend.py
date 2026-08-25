"""Trend factor calculator."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


def ema_slope(closes: list[Decimal], period: int = 10) -> Decimal:
    closes = [D(c) for c in closes]
    if len(closes) < period + 1:
        return D("0")
    ema = closes[0]
    k = D("2") / D(str(period + 1))
    values = [ema]
    for price in closes[1:]:
        ema = price * k + ema * (D("1") - k)
        values.append(ema)
    return values[-1] - values[-2]


def ma_distance(closes: list[Decimal], period: int = 20) -> Decimal:
    closes = [D(c) for c in closes]
    if len(closes) < period:
        return D("0")
    ma = sum(closes[-period:], D("0")) / D(str(period))
    return (closes[-1] - ma) / ma if ma > 0 else D("0")


def trend_strength(closes: list[Decimal]) -> Decimal:
    slope = ema_slope(closes)
    distance = ma_distance(closes)
    strength = max(D("-1"), min(D("1"), slope * D("100") + distance * D("10")))
    return strength


def calculate(symbol: str, timeframe: str, candles: list[dict]) -> dict:
    closes = [D(str(c.get("close", c.get("c", "0")))) for c in candles]
    strength = trend_strength(closes)
    return {
        "factor_name": "trend",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": strength,
        "confidence": D("0.8") if len(closes) >= 20 else D("0.5"),
        "metadata": {"ema_slope": str(ema_slope(closes)), "ma_distance": str(ma_distance(closes))},
    }
