"""Funding payment calculator. Long pays when funding > 0; Short pays when < 0."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.perpetual.domain import FundingPayment, MarginPosition, PositionSide


class FundingCalculator:
    def payment(
        self,
        position: MarginPosition,
        rate: Decimal,
        mark_price: Decimal,
        contract_size: Decimal = Decimal("1"),
    ) -> FundingPayment:
        if position.is_flat:
            return FundingPayment(
                symbol=position.symbol,
                position_side=PositionSide.FLAT,
                amount=Decimal("0"),
                rate=D(rate),
                notional=Decimal("0"),
            )
        notional = ExposureService.calculate(
            quantity=position.quantity,
            price=mark_price,
            spec=InstrumentExposureSpec(
                instrument_type="LINEAR_PERP",
                contract_size=D(contract_size),
            ),
            side=position.side.value,
        ).gross_notional
        raw = notional * D(rate)
        if position.side == PositionSide.LONG:
            amount = -raw
        else:
            amount = raw
        return FundingPayment(
            symbol=position.symbol,
            position_side=position.side,
            amount=amount,
            rate=D(rate),
            notional=notional,
        )

    def apply_to_position(self, position: MarginPosition, payment: FundingPayment) -> None:
        if payment.amount > 0:
            position.funding_received += payment.amount
        else:
            position.funding_paid += -payment.amount
        position.realized_pnl += payment.amount
