"""Position sizing: advisory only. Outputs recommended_position."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.alpha.meta_decision import MetaDecision
from crypto_trader.alpha.sub_strategy.base import AlphaSide
from crypto_trader.domain.money import D


def recommend_position(
    meta: MetaDecision,
    *,
    account_equity,
    price,
    volatility,
    risk_per_trade: str = "0.01",
    max_position_notional=None,
) -> Decimal:
    """Fractional risk sizing, LONG/SHORT symmetric.

    position = (equity * risk_per_trade * confidence) / (volatility * price)
    """
    if meta.side == AlphaSide.NO_TRADE:
        return D("0")
    equity = D(account_equity)
    price = D(price)
    vol = D(volatility)
    if equity <= 0 or price <= 0 or vol <= 0:
        return D("0")
    risk_budget = equity * D(risk_per_trade) * meta.confidence
    stop_distance = max(vol * price * D("2"), price * D("0.001"))
    quantity = risk_budget / stop_distance
    notional = quantity * price
    max_notional = D(max_position_notional) if max_position_notional is not None else None
    if max_notional is not None and notional > max_notional:
        quantity = max_notional / price
    return max(quantity, D("0"))
