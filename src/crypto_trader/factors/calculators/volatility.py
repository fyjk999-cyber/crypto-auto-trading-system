"""Volatility factor calculator."""

from __future__ import annotations

from crypto_trader.domain.money import D


def calculate(symbol: str, timeframe: str, candles: list[dict]) -> dict:
    closes = [D(str(c.get("close", c.get("c", "0")))) for c in candles]
    highs = [D(str(c.get("high", c.get("h", c.get("close", c.get("c", "0")))))) for c in candles]
    lows = [D(str(c.get("low", c.get("l", c.get("close", c.get("c", "0")))))) for c in candles]
    if len(closes) < 2:
        return {
            "factor_name": "volatility",
            "symbol": symbol,
            "timeframe": timeframe,
            "value": D("0"),
            "confidence": D("0"),
        }
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    rv = (
        (sum((r * r for r in returns), D("0")) / D(str(len(returns)))).sqrt() if returns else D("0")
    )
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = sum(trs, D("0")) / D(str(len(trs))) if trs else D("0")
    value = min(D("1"), rv * D("10") + atr * D("0.2"))
    return {
        "factor_name": "volatility",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": value,
        "confidence": D("0.85") if len(returns) >= 10 else D("0.4"),
        "metadata": {"realized_volatility": str(rv), "atr": str(atr)},
    }
