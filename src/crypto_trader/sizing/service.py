"""Canonical deterministic sizing contract for Live-LLM entry proposals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.domain.money import D, floor_to_step
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.risk.leverage import clamp_leverage
from crypto_trader.sizing.risk_normalized import calculate_risk_normalized_size


@dataclass(frozen=True)
class CanonicalSize:
    requested_notional: Decimal
    risk_normalized_notional: Decimal
    normalized_quantity: Decimal
    requested_leverage: Decimal
    risk_bounded_leverage: Decimal
    max_loss_estimate: Decimal
    portfolio_exposure_after_trade: Decimal
    sizing_reason_codes: tuple[str, ...]


class LiveEntrySizingService:
    def __init__(
        self,
        *,
        risk_fraction: Decimal = Decimal("0.005"),
        max_order_notional: Decimal = Decimal("1000000"),
        max_leverage: Decimal = Decimal("5"),
    ) -> None:
        self.risk_fraction = D(risk_fraction)
        self.max_order_notional = D(max_order_notional)
        self.max_leverage = D(max_leverage)

    def size(
        self,
        *,
        side: str,
        requested_quantity: Decimal,
        requested_exposure: Decimal | None = None,
        requested_leverage: Decimal,
        account: Account,
        positions: dict[str, Position],
        instrument: Instrument,
        price: Decimal,
        stop_price: Decimal | None,
        volatility: Decimal = Decimal("0"),
        liquidity: Decimal = Decimal("1"),
    ) -> CanonicalSize:
        requested_quantity = D(requested_quantity)
        requested_leverage = D(requested_leverage or "1")
        price = D(price)
        contract_size = D(instrument.contract_size)
        multiplier = D(instrument.contract_multiplier)
        lot_size = D(instrument.step_size)
        requested_exposure = D(requested_exposure or "0")
        if price <= 0 or account.equity <= 0:
            return _zero(requested_leverage, "INVALID_SIZING_INPUT")
        spec = InstrumentExposureSpec(
            instrument_type=instrument.instrument_type,
            contract_size=contract_size,
            contract_multiplier=multiplier,
        )
        if requested_quantity <= 0 and requested_exposure > 0:
            requested_quantity = requested_exposure / (
                price * contract_size * multiplier
            )
        if requested_quantity <= 0:
            return _zero(requested_leverage, "INVALID_SIZING_INPUT")
        requested_notional = ExposureService.calculate(
            quantity=requested_quantity,
            price=price,
            spec=spec,
            side=side,
        ).gross_notional
        stop_distance = abs(price - D(stop_price)) if stop_price is not None else Decimal("0")
        reasons: list[str] = []
        quantity = requested_quantity
        if stop_distance > 0:
            normalized = calculate_risk_normalized_size(
                equity=account.equity,
                risk_fraction=self.risk_fraction,
                price=price,
                stop_distance=stop_distance,
                contract_size=contract_size * multiplier,
                lot_size=lot_size,
                max_notional=self.max_order_notional,
            )
            quantity = min(quantity, normalized.quantity)
            reasons.append("STOP_DISTANCE_RISK_BUDGET")
        if requested_notional > self.max_order_notional:
            cap = self.max_order_notional / (price * contract_size * multiplier)
            quantity = min(quantity, cap)
            reasons.append("MAX_ORDER_NOTIONAL")
        quantity = floor_to_step(quantity, lot_size)
        if quantity <= 0:
            return _zero(requested_leverage, "BELOW_MINIMUM_LOT")
        normalized_notional = ExposureService.calculate(
            quantity=quantity,
            price=price,
            spec=spec,
            side=side,
        ).gross_notional
        existing = sum(
            (
                ExposureService.for_position(position).gross_notional
                for position in positions.values()
            ),
            Decimal("0"),
        )
        bounded_leverage = clamp_leverage(
            requested=requested_leverage,
            max_leverage=self.max_leverage,
            volatility=volatility,
            liquidity=liquidity,
        )
        if bounded_leverage < requested_leverage:
            reasons.append("LEVERAGE_CLAMPED")
        max_loss = (
            quantity * stop_distance * contract_size * multiplier
            if stop_distance > 0
            else Decimal("0")
        )
        return CanonicalSize(
            requested_notional=requested_notional,
            risk_normalized_notional=normalized_notional,
            normalized_quantity=quantity,
            requested_leverage=requested_leverage,
            risk_bounded_leverage=bounded_leverage,
            max_loss_estimate=max_loss,
            portfolio_exposure_after_trade=existing + normalized_notional,
            sizing_reason_codes=tuple(reasons or ["REQUEST_WITHIN_BOUNDS"]),
        )


def _zero(requested_leverage: Decimal, reason: str) -> CanonicalSize:
    return CanonicalSize(
        requested_notional=Decimal("0"),
        risk_normalized_notional=Decimal("0"),
        normalized_quantity=Decimal("0"),
        requested_leverage=requested_leverage,
        risk_bounded_leverage=Decimal("0"),
        max_loss_estimate=Decimal("0"),
        portfolio_exposure_after_trade=Decimal("0"),
        sizing_reason_codes=(reason,),
    )
