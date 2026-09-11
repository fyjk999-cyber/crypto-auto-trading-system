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
    def for_mapping(position: Mapping[str, object]) -> Exposure:
        """Calculate from factual position fields, with legacy notional compatibility.

        When quantity is present it is authoritative and a caller-provided
        ``notional`` value is deliberately ignored. This keeps reporting and
        risk analytics on the same contract-size-aware definition.
        """

        if "quantity" not in position:
            gross = abs(D(position.get("notional", "0")))
            side = str(position.get("side") or "LONG").upper()
            return Exposure(
                gross_notional=gross,
                signed_notional=-gross if side == "SHORT" else gross,
            )
        quantity = D(position["quantity"])
        instrument_type = str(position.get("instrument_type") or "SPOT")
        raw_price = (
            position.get("mark_price")
            or position.get("price")
            or position.get("avg_entry_price")
        )
        inverse = instrument_type.upper() in {
            "INVERSE",
            "INVERSE_PERP",
            "INVERSE_FUTURES",
        }
        if raw_price is None and not inverse:
            raise ValueError("canonical exposure requires a factual position price")
        if instrument_type.upper() == "LINEAR_PERP":
            contract_size = _required_linear_spec(position, "contract_size")
            contract_multiplier = _required_linear_spec(
                position, "contract_multiplier"
            )
        else:
            contract_size = D(position.get("contract_size", "1"))
            contract_multiplier = D(position.get("contract_multiplier", "1"))
        return ExposureService.calculate(
            quantity=quantity,
            price=raw_price or "1",
            spec=InstrumentExposureSpec(
                instrument_type=instrument_type,
                contract_size=contract_size,
                contract_multiplier=contract_multiplier,
            ),
            side="LONG" if quantity >= 0 else "SHORT",
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


def _required_linear_spec(position: Mapping[str, object], key: str) -> Decimal:
    raw = position.get(key)
    if raw in (None, ""):
        raise ValueError(f"LINEAR_PERP position missing factual {key}")
    value = D(raw)
    if not value.is_finite() or value <= 0:
        raise ValueError(f"LINEAR_PERP position has invalid {key}")
    return value
