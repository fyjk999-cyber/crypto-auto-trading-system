"""Canonical exposure calculations shared by PAPER trading components."""

from __future__ import annotations

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
        gross = abs(quantity) * price * multiplier
        if side not in {"LONG", "SHORT"}:
            raise ValueError("exposure side must be LONG or SHORT")
        return Exposure(gross_notional=gross, signed_notional=gross if side == "LONG" else -gross)
