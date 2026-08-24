"""Margin engine: initial margin, maintenance margin, available margin, ratio."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from crypto_trader.domain.money import D
from crypto_trader.perpetual.domain import (
    MarginPosition,
    MarginRatio,
    PerpetualContract,
    PositionSide,
)


class MarginState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance: Decimal = Decimal("0")
    positions: list[MarginPosition] = []

    def position_notional(self) -> Decimal:
        return sum((p.notional() for p in self.positions if not p.is_flat), Decimal("0"))

    def total_initial_margin(self) -> Decimal:
        return sum((p.initial_margin for p in self.positions if not p.is_flat), Decimal("0"))

    def total_maintenance_margin(self) -> Decimal:
        return sum((p.maintenance_margin for p in self.positions if not p.is_flat), Decimal("0"))

    def total_unrealized_pnl(self) -> Decimal:
        return sum((p.unrealized_pnl for p in self.positions if not p.is_flat), Decimal("0"))


class MarginCalculator:
    """Tiered-margin-ready isolated margin calculator.

    initial_margin = notional / effective_leverage, but the calculator accepts
    a margin-rate provider so exchange tier rules can be plugged in later.
    """

    def __init__(self, tier_provider=None) -> None:
        self.tier_provider = tier_provider

    def effective_leverage(self, leverage: Decimal, max_leverage: Decimal) -> Decimal:
        lev = D(leverage)
        if lev <= 0:
            lev = D("1")
        return min(lev, D(max_leverage))

    def initial_margin(
        self,
        contract: PerpetualContract,
        quantity: Decimal,
        entry_price: Decimal,
        leverage: Decimal,
    ) -> Decimal:
        qty = D(quantity)
        price = D(entry_price)
        lev = self.effective_leverage(leverage, contract.max_leverage)
        notional = abs(qty) * price * contract.contract_size
        if self.tier_provider is not None:
            rate = self.tier_provider(contract.symbol, notional)
            return notional * rate
        return notional / lev

    def maintenance_margin(
        self,
        contract: PerpetualContract,
        quantity: Decimal,
        entry_price: Decimal,
        rate: str | None = None,
    ) -> Decimal:
        notional = abs(D(quantity)) * D(entry_price) * contract.contract_size
        maintenance_rate = D(rate) if rate else self._default_maintenance_rate(notional)
        return notional * maintenance_rate

    def _default_maintenance_rate(self, notional: Decimal) -> Decimal:
        if notional >= D("1000000"):
            return D("0.005")
        if notional >= D("100000"):
            return D("0.0025")
        return D("0.001")

    def available_margin(self, state: MarginState, total_balance: Decimal) -> Decimal:
        used = state.total_initial_margin()
        return D(total_balance) - used

    def margin_ratio(self, state: MarginState, total_balance: Decimal) -> MarginRatio:
        maintenance = state.total_maintenance_margin()
        if maintenance <= 0:
            return MarginRatio(value=D("999"), healthy=True)
        equity = D(total_balance) + state.total_unrealized_pnl()
        ratio = equity / maintenance
        return MarginRatio(value=ratio, healthy=ratio >= D("1"))

    def position_equity(self, position: MarginPosition) -> Decimal:
        return position.initial_margin + position.unrealized_pnl

    def liquidation_distance(
        self, position: MarginPosition, contract: PerpetualContract
    ) -> Decimal:
        if position.is_flat or position.quantity == 0:
            return Decimal("0")
        maintenance = position.maintenance_margin
        if position.side == PositionSide.LONG:
            per_qty = abs(position.quantity) * contract.contract_size
            if per_qty <= 0:
                return Decimal("0")
            return (position.initial_margin - maintenance) / per_qty
        per_qty = abs(position.quantity) * contract.contract_size
        if per_qty <= 0:
            return Decimal("0")
        return (position.initial_margin - maintenance) / per_qty
