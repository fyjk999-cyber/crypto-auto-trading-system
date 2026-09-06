"""Canonical exposure calculations shared by PAPER trading components."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass(frozen=True)
class InstrumentExposureSpec:
    instrument_type: str
    contract_size: Decimal = Decimal("1")
    contract_multiplier: Decimal = Decimal("1")


@dataclass(frozen=True)
class Exposure:
    gross_notional: Decimal
    signed_notional: Decimal


class ExposureService:
    @staticmethod
    def calculate(*, quantity, price, spec: InstrumentExposureSpec, side: str) -> Exposure:
        quantity, price = D(quantity), D(price)
        multiplier = D(spec.contract_size) * D(spec.contract_multiplier)
        instrument_type = spec.instrument_type.upper()
        if instrument_type in {"INVERSE", "INVERSE_PERP", "INVERSE_FUTURES"}:
            gross = abs(quantity) * multiplier
        else:
            gross = abs(quantity) * price * multiplier
        if side not in {"LONG", "SHORT"}:
            raise ValueError("exposure side must be LONG or SHORT")
        return Exposure(gross_notional=gross, signed_notional=gross if side == "LONG" else -gross)

    @staticmethod
    def for_position(position, *, price=None) -> Exposure:
        quantity = D(position.quantity)
        side = "LONG" if quantity >= 0 else "SHORT"
        valuation_price = D(price or position.avg_entry_price or "0")
        if valuation_price <= 0 and D(position.cost_basis) > 0:
            gross = abs(D(position.cost_basis))
            return Exposure(
                gross_notional=gross,
                signed_notional=gross if side == "LONG" else -gross,
            )
        return ExposureService.calculate(
            quantity=quantity,
            price=valuation_price,
            spec=InstrumentExposureSpec(
                instrument_type=position.instrument_type,
                contract_size=D(position.contract_size),
                contract_multiplier=D(position.contract_multiplier),
            ),
            side=side,
        )

    @staticmethod
    def for_portfolio(
        positions: Mapping[str, object],
        *,
        prices: Mapping[str, Decimal] | None = None,
    ) -> Exposure:
        prices = prices or {}
        gross = Decimal("0")
        signed = Decimal("0")
        for symbol, position in positions.items():
            exposure = ExposureService.for_position(
                position,
                price=prices.get(symbol),
            )
            gross += exposure.gross_notional
            signed += exposure.signed_notional
        return Exposure(gross_notional=gross, signed_notional=signed)
