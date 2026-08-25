"""Capital distribution from allocations."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


def distribute_capital(equity, allocations: list) -> dict[str, Decimal]:
    eq = D(equity)
    total_weight = sum((D(str(a.weight_pct)) for a in allocations), D("0"))
    if total_weight <= 0:
        return {}
    return {a.symbol: eq * D(str(a.weight_pct)) / total_weight for a in allocations}
