"""Open interest factor calculator."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


def calculate(
    symbol: str,
    timeframe: str,
    oi_current: Decimal,
    oi_previous: Decimal | None = None,
    price_change: Decimal | None = None,
) -> dict:
    current = D(oi_current)
    previous = D(oi_previous) if oi_previous is not None else current
    change = (current - previous) / previous if previous > 0 else D("0")
    divergence = D("0")
    if price_change is not None:
        price = D(price_change)
        if price > 0 and change < 0:
            divergence = D("0.7")  # price up, OI down: weak rally
        elif price < 0 and change > 0:
            divergence = D("-0.7")  # price down, OI up: strong downtrend
    value = max(D("-1"), min(D("1"), change * D("10") - divergence))
    return {
        "factor_name": "open_interest",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": value,
        "confidence": D("0.7") if oi_previous is not None else D("0.4"),
        "metadata": {"oi_change": str(change), "price_oi_divergence": str(divergence)},
    }
