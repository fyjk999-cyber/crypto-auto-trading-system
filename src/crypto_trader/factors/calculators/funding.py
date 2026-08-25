"""Funding factor calculator."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


def calculate(
    symbol: str, timeframe: str, funding_rate: Decimal, average_funding: Decimal | None = None
) -> dict:
    rate = D(funding_rate)
    avg = D(average_funding) if average_funding is not None else D("0.0001")
    anomaly = max(D("0"), min(D("1"), abs(rate - avg) / max(abs(avg), D("0.00001"))))
    value = max(D("-1"), min(D("1"), rate * D("10000")))
    return {
        "factor_name": "funding",
        "symbol": symbol,
        "timeframe": timeframe,
        "value": value,
        "confidence": D("0.7"),
        "metadata": {"funding_rate": str(rate), "funding_anomaly": str(anomaly)},
    }
