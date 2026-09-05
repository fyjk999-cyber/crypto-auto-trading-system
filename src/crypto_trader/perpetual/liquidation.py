"""Liquidation price and liquidation processing."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from crypto_trader.domain.money import D
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.perpetual.domain import (
    LiquidationPrice,
    MarginPosition,
    PerpetualContract,
    PositionSide,
)


class LiquidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: PositionSide
    liquidated: bool
    liquidation_price: Decimal
    bankruptcy_price: Decimal
    remaining_equity: Decimal
    fee: Decimal


class LiquidationCalculator:
    def __init__(self, liquidation_fee_rate: str = "0.0005") -> None:
        self.liquidation_fee_rate = D(liquidation_fee_rate)

    def liquidation_price(
        self, position: MarginPosition, contract: PerpetualContract
    ) -> LiquidationPrice:
        if position.is_flat or position.quantity == 0:
            return LiquidationPrice(
                value=D("0"),
                side=position.side,
                margin_mode=position.margin_mode,
                distance_pct=D("0"),
            )
        qty = abs(position.quantity) * contract.contract_size
        if qty <= 0:
            return LiquidationPrice(
                value=D("0"),
                side=position.side,
                margin_mode=position.margin_mode,
                distance_pct=D("0"),
            )
        maintenance = position.maintenance_margin
        price = position.avg_entry_price
        if position.side == PositionSide.LONG:
            liq = price - (position.initial_margin - maintenance) / qty
        else:
            liq = price + (position.initial_margin - maintenance) / qty
        distance = (liq - price) / price if price > 0 else D("0")
        return LiquidationPrice(
            value=liq, side=position.side, margin_mode=position.margin_mode, distance_pct=distance
        )

    def evaluate(
        self, position: MarginPosition, contract: PerpetualContract, mark_price: Decimal
    ) -> LiquidationResult:
        if position.is_flat:
            return LiquidationResult(
                symbol=position.symbol,
                side=position.side,
                liquidated=False,
                liquidation_price=D("0"),
                bankruptcy_price=D("0"),
                remaining_equity=D("0"),
                fee=D("0"),
            )
        liq = self.liquidation_price(position, contract)
        liquidated = (position.side == PositionSide.LONG and D(mark_price) <= liq.value) or (
            position.side == PositionSide.SHORT and D(mark_price) >= liq.value
        )
        notional = ExposureService.calculate(
            quantity=position.quantity,
            price=mark_price,
            spec=InstrumentExposureSpec(
                instrument_type="LINEAR_PERP",
                contract_size=contract.contract_size,
            ),
            side=position.side.value,
        ).gross_notional
        fee = notional * self.liquidation_fee_rate
        if position.side == PositionSide.LONG:
            bankruptcy = position.avg_entry_price - position.initial_margin / (
                abs(position.quantity) * contract.contract_size
            )
        else:
            bankruptcy = position.avg_entry_price + position.initial_margin / (
                abs(position.quantity) * contract.contract_size
            )
        remaining = max(position.initial_margin + position.unrealized_pnl - fee, D("0"))
        return LiquidationResult(
            symbol=position.symbol,
            side=position.side,
            liquidated=liquidated,
            liquidation_price=liq.value,
            bankruptcy_price=bankruptcy,
            remaining_equity=remaining,
            fee=fee,
        )
