"""Slippage prediction model."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


class SlippageModel:
    def predict_bps(
        self,
        *,
        order_size: Decimal,
        orderbook_depth: Decimal,
        spread_bps: Decimal,
        volatility_pct: Decimal,
        liquidity_score: Decimal,
    ) -> Decimal:
        size = D(order_size)
        depth = D(orderbook_depth)
        if depth <= 0:
            return D("999")
        size_pressure = size / depth * D("100")
        vol = D(volatility_pct)
        liq = D(liquidity_score)
        return (
            size_pressure * D("0.5")
            + D(spread_bps) * D("0.2")
            + vol * D("0.3")
            + max(D("0"), D("5") - liq)
        )
