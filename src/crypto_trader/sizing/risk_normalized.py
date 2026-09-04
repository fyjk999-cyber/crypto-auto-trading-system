"""Conservative quantity sizing from explicit risk inputs, not a fixed default."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D, floor_to_step


@dataclass(frozen=True)
class RiskNormalizedSize:
    quantity: Decimal
    risk_budget: Decimal
    stop_distance: Decimal
    gross_notional: Decimal


def calculate_risk_normalized_size(
    *,
    equity,
    risk_fraction,
    price,
    stop_distance,
    contract_size="1",
    lot_size="0.00000001",
    max_notional: Decimal | None = None,
) -> RiskNormalizedSize:
    equity, fraction, price, distance = D(equity), D(risk_fraction), D(price), D(stop_distance)
    contract_size, lot_size = D(contract_size), D(lot_size)
    if min(equity, fraction, price, distance, contract_size, lot_size) <= 0:
        return RiskNormalizedSize(Decimal("0"), Decimal("0"), distance, Decimal("0"))
    risk_budget = equity * fraction
    quantity = risk_budget / (distance * contract_size)
    notional = quantity * price * contract_size
    if max_notional is not None and notional > D(max_notional):
        quantity = D(max_notional) / (price * contract_size)
        notional = quantity * price * contract_size
    quantity = floor_to_step(quantity, lot_size)
    return RiskNormalizedSize(quantity, risk_budget, distance, quantity * price * contract_size)
