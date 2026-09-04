"""Deterministic leverage clamp; LLM confidence is never used as leverage."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


def clamp_leverage(*, requested, max_leverage, volatility="0", liquidity="1") -> Decimal:
    requested, maximum = D(requested or "1"), D(max_leverage)
    if maximum <= 0:
        return Decimal("0")
    requested = max(Decimal("1"), requested)
    volatility, liquidity = D(volatility), D(liquidity)
    cap = maximum
    if volatility >= D("0.05"):
        cap = min(cap, Decimal("1"))
    if liquidity <= D("0"):
        cap = min(cap, Decimal("1"))
    return min(requested, cap)
