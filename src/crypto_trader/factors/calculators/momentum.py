"""Momentum factor calculator."""

from __future__ import annotations

from crypto_trader.domain.money import D


def calculate(symbol: str, timeframe: str, candles: list[dict]) -> dict:
    closes = [D(str(c.get("close", c.get("c", "0")))) for c in candles]
    if len(closes) < 2:
        return {
            "factor_name": "momentum",
            "symbol": symbol,
            "timeframe": timeframe,
            "value": D("0"),
            "confidence": D("0"),
        }
    ret = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else D("0")
    acc = D("0")
    if len(closes) >= 3 and closes[-3] > 0:
        prev_ret = (closes[-2] - closes[-3]) / closes[-3]
        acc = ret - prev_ret
    volume_conf = D("0")
    if candles and "volume" in candles[-1]:
        vols = [D(str(c.get("volume", "0"))) for c in candles]
        if len(vols) >= 2 and vols[-2] > 0:
            vol_ratio = vols[-1] / vols[-2]
            volume_conf = min(D("1"), vol_ratio / D("2"))
    value = max(D("-1"), min(D("1"), ret * D("100") + acc * D("50")))
    confidence = D("0.6") if volume_conf == 0 else min(D("0.9"), D("0.5") + volume_conf * D("0.4"))
    return {
        "factor_name": "momentum",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": value,
        "confidence": confidence,
        "metadata": {
            "return": str(ret),
            "acceleration": str(acc),
            "volume_confirmation": str(volume_conf),
        },
    }
