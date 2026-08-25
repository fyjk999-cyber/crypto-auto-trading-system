"""Volume factor calculator."""

from __future__ import annotations

from crypto_trader.domain.money import D


def calculate(symbol: str, timeframe: str, candles: list[dict]) -> dict:
    if not candles or "volume" not in candles[0]:
        return {
            "factor_name": "volume",
            "symbol": symbol,
            "timeframe": timeframe,
            "value": D("0"),
            "confidence": D("0"),
        }
    vols = [D(str(c.get("volume", "0"))) for c in candles]
    if len(vols) < 2:
        return {
            "factor_name": "volume",
            "symbol": symbol,
            "timeframe": timeframe,
            "value": D("0"),
            "confidence": D("0"),
        }
    recent = vols[-1]
    baseline = sum(vols[:-1], D("0")) / D(str(len(vols) - 1)) if len(vols) > 1 else D("0")
    if baseline <= 0:
        return {
            "factor_name": "volume",
            "symbol": symbol,
            "timeframe": timeframe,
            "value": D("0"),
            "confidence": D("0"),
        }
    change = (recent - baseline) / baseline
    anomaly = min(D("1"), abs(change) / D("3"))
    value = max(D("-1"), min(D("1"), change * D("0.5")))
    return {
        "factor_name": "volume",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": value,
        "confidence": min(D("0.9"), D("0.5") + anomaly * D("0.4")),
        "metadata": {"volume_change": str(change), "volume_anomaly": str(anomaly)},
    }
