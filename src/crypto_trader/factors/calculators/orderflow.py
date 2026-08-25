"""Orderflow factor calculator."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


def calculate(
    symbol: str,
    timeframe: str,
    candles: list[dict],
    bid_volume: Decimal = Decimal("0"),
    ask_volume: Decimal = Decimal("0"),
) -> dict:
    bid = D(bid_volume)
    ask = D(ask_volume)
    total = bid + ask
    imbalance = (bid - ask) / total if total > 0 else D("0")
    # fallback: infer buy pressure from candle closes vs midpoint when no book data
    if total == 0 and len(candles) >= 2:
        buy_pressure = D("0")
        for c in candles[-10:]:
            close = D(str(c.get("close", c.get("c", "0"))))
            open_ = D(str(c.get("open", c.get("o", close))))
            if close > open_:
                buy_pressure += D("1")
            elif close < open_:
                buy_pressure -= D("1")
        imbalance = max(D("-1"), min(D("1"), buy_pressure / D("10")))
    return {
        "factor_name": "orderflow",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": max(D("-1"), min(D("1"), imbalance)),
        "confidence": D("0.75") if total > 0 else D("0.4"),
        "metadata": {
            "bid_volume": str(bid),
            "ask_volume": str(ask),
            "orderbook_imbalance": str(imbalance),
        },
    }
