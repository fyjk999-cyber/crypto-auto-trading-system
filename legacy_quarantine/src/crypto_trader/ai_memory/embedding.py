"""Deterministic market state embedding (no external model)."""

from __future__ import annotations

from crypto_trader.domain.money import D


def embed_market_state(state: dict) -> tuple[float, ...]:
    price = float(D(str(state.get("price", "0"))))
    volume = float(D(str(state.get("volume", "0"))))
    volatility = float(D(str(state.get("volatility", "0"))))
    funding = float(D(str(state.get("funding", "0"))))
    oi = float(D(str(state.get("oi", "0"))))
    regime = float({"BULL": 1.0, "BEAR": -1.0}.get(state.get("regime", "RANGE"), 0.0))
    return (price, volume, volatility, funding, oi, regime)
