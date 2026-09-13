"""ScaleInSizer: the deterministic quantity authority for an ADD (§99-§107).

    AddRiskBudget = RemainingCampaignRiskBudget
                    x ConvictionMultiplier
                    x RegimeMultiplier
                    x DrawdownMultiplier

    AddRiskQty    = AddRiskBudget / EffectiveStopDistance

    FinalAddQty   = floor_to_step(min(
        AddRiskQty,
        Remaining5xQty,          # §84/§105 cumulative position ceiling
        RemainingPortfolioQty,   # §85/§107 portfolio gross ceiling
        MarginCapQty,            # §106
        LiquidityCapQty,         # §101 factual depth x participation
        SymbolCapQty,
    ))

with

    EffectiveStopDistance = max(
        |price - llm stop|,
        MinimumValidStopDistance,   # §97/§98 deterministic floor
    )

The LLM's ``requested_quantity`` / ``requested_exposure`` are advisory only and
never cap the result. A sub-economic ADD is REJECTED, never rounded up (§100).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.models import Instrument
from crypto_trader.domain.money import D, floor_to_step
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.scale_in.campaign import CampaignProjection, PositionCampaign
from crypto_trader.scale_in.policy import ScaleInPolicy
from crypto_trader.sizing.audit import (
    BINDING_LIQUIDITY,
    BINDING_MARGIN,
    BINDING_NOTIONAL_CAP,
    BINDING_SYMBOL,
)
from crypto_trader.sizing.conviction import conviction_multiplier
from crypto_trader.sizing.policy import PositionSizingPolicy

# ---- rejection codes
ADD_BELOW_ECONOMIC_NOTIONAL = "ADD_BELOW_ECONOMIC_NOTIONAL"
ADD_BELOW_MINIMUM_LOT = "ADD_BELOW_MINIMUM_LOT"
ADD_INVALID_SIZING_INPUT = "ADD_INVALID_SIZING_INPUT"
ADD_LIQUIDITY_UNKNOWN = "ADD_LIQUIDITY_UNKNOWN"
ADD_INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN_FOR_SCALE_IN"
ADD_POSITION_CEILING_REACHED = "MAX_POSITION_NOTIONAL_REACHED"
ADD_PORTFOLIO_CEILING_REACHED = "PORTFOLIO_EXPOSURE_CAP"
ADD_RISK_BUDGET_EXHAUSTED = "CAMPAIGN_RISK_BUDGET_EXHAUSTED"
ADD_STOP_DISTANCE_INVALID = "ADD_STOP_DISTANCE_INVALID"

#: Binding-cap taxonomy for an ADD (mirrors the entry taxonomy).
BINDING_ADD_RISK_BUDGET = "ADD_RISK_BUDGET"
BINDING_ADD_POSITION_CAP = "ADD_5X_REMAINING"
BINDING_ADD_PORTFOLIO_CAP = "ADD_PORTFOLIO_REMAINING"
BINDING_ADD_ECONOMIC_MINIMUM = "ECONOMIC_MINIMUM"
BINDING_ADD_NONE = "NONE"

ADD_CAP_ORDER = (
    BINDING_ADD_RISK_BUDGET,
    BINDING_LIQUIDITY,
    BINDING_MARGIN,
    BINDING_ADD_PORTFOLIO_CAP,
    BINDING_ADD_POSITION_CAP,
    BINDING_SYMBOL,
    BINDING_NOTIONAL_CAP,
)


@dataclass(frozen=True)
class ScaleInSize:
    """Deterministic ADD size, with the full explanation attached."""

    rejected: bool
    approved_quantity: Decimal
    approved_notional: Decimal
    reason_codes: tuple[str, ...]
    binding_cap: str
    binding_caps: tuple[str, ...]
    effective_stop_distance: Decimal
    minimum_valid_stop_distance: Decimal
    stop_distance_was_widened: bool
    risk_budget: Decimal
    risk_quantity: Decimal
    leverage_cap_quantity: Decimal
    portfolio_cap_quantity: Decimal
    margin_cap_quantity: Decimal
    liquidity_cap_quantity: Decimal
    symbol_cap_quantity: Decimal
    projection: CampaignProjection | None
    equity: Decimal | None
    available_margin: Decimal | None
    liquidity_depth: Decimal | None
    approved_leverage: Decimal
    max_loss_estimate: Decimal
    min_effective_notional: Decimal
    notional_pct_of_equity: Decimal | None
    add_number: int

    def to_evidence(self) -> dict:
        return {
            "rejected": self.rejected,
            "approved_add_qty": str(self.approved_quantity),
            "approved_add_notional": str(self.approved_notional),
            "reason_codes": list(self.reason_codes),
            "binding_cap": self.binding_cap,
            "binding_caps": list(self.binding_caps),
            "effective_stop_distance": str(self.effective_stop_distance),
            "minimum_valid_stop_distance": str(self.minimum_valid_stop_distance),
            "stop_distance_was_widened": self.stop_distance_was_widened,
            "add_risk_budget": str(self.risk_budget),
            "add_risk_qty": str(self.risk_quantity),
            "remaining_5x_qty": str(self.leverage_cap_quantity),
            "remaining_portfolio_qty": str(self.portfolio_cap_quantity),
            "margin_cap_qty": str(self.margin_cap_quantity),
            "liquidity_cap_qty": str(self.liquidity_cap_quantity),
            "symbol_cap_qty": str(self.symbol_cap_quantity),
            "approved_leverage": str(self.approved_leverage),
            "max_loss_estimate": str(self.max_loss_estimate),
            "min_effective_notional": str(self.min_effective_notional),
            "notional_pct_of_equity": _s(self.notional_pct_of_equity),
            "add_number": self.add_number,
            "projection": self.projection.to_evidence() if self.projection else None,
        }


class ScaleInSizer:
    """Computes the authoritative ADD quantity. Never selects a direction."""

    def __init__(
        self,
        *,
        policy: PositionSizingPolicy,
        scale_in_policy: ScaleInPolicy,
    ) -> None:
        self.policy = policy
        self.scale_in_policy = scale_in_policy

    def size(
        self,
        *,
        campaign: PositionCampaign,
        instrument: Instrument,
        price: Decimal,
        stop_loss: Decimal | None,
        conviction: Decimal,
        liquidity_depth_qty: Decimal | None,
        equity: Decimal | None,
        available_margin: Decimal | None,
        requested_leverage: Decimal,
        positions: dict | None = None,
        volatility: Decimal | None = None,
        liquidity: Decimal = Decimal("1"),
        regime_multiplier: Decimal = Decimal("1"),
        drawdown_multiplier: Decimal = Decimal("1"),
        campaign_risk_budget: Decimal | None = None,
    ) -> ScaleInSize:
        policy = self.policy
        scale_policy = self.scale_in_policy
        price = _finite(price)
        stop = _finite(stop_loss)
        conviction = _finite(conviction)
        equity_value = _finite_or_none(equity)
        margin_value = _finite_or_none(available_margin)
        depth_value = _finite_or_none(liquidity_depth_qty)
        add_number = int(campaign.add_count) + 1

        # ONE campaign budget, and it must be the SAME number the gates used:
        # a sizer that re-derives its own budget could authorise an ADD the
        # gates already refused (or vice versa).
        budget = (
            D(campaign_risk_budget)
            if campaign_risk_budget is not None
            else scale_policy.campaign_risk_budget(
                equity_value or Decimal("0"), policy.max_risk_per_trade
            )
        )
        # §87 — the reserve set aside for adds is an ADDITIONAL ceiling on one
        # add, so the initial entry can never be re-spent as scale-in room.
        reserve = budget * scale_policy.scale_in_risk_share

        def reject(reason: str, **overrides) -> ScaleInSize:
            base = dict(
                rejected=True,
                approved_quantity=Decimal("0"),
                approved_notional=Decimal("0"),
                reason_codes=(reason,),
                binding_cap=BINDING_ADD_NONE,
                binding_caps=(),
                effective_stop_distance=Decimal("0"),
                minimum_valid_stop_distance=Decimal("0"),
                stop_distance_was_widened=False,
                risk_budget=budget,
                risk_quantity=Decimal("0"),
                leverage_cap_quantity=Decimal("0"),
                portfolio_cap_quantity=Decimal("0"),
                margin_cap_quantity=Decimal("0"),
                liquidity_cap_quantity=Decimal("0"),
                symbol_cap_quantity=Decimal("0"),
                projection=None,
                equity=equity_value,
                available_margin=margin_value,
                liquidity_depth=depth_value,
                approved_leverage=Decimal("0"),
                max_loss_estimate=Decimal("0"),
                min_effective_notional=(
                    policy.min_effective_notional(equity_value)
                    if equity_value is not None
                    else Decimal("0")
                ),
                notional_pct_of_equity=None,
                add_number=add_number,
            )
            base.update(overrides)
            return ScaleInSize(**base)

        if price <= 0 or equity_value is None or equity_value <= 0:
            return reject(ADD_INVALID_SIZING_INPUT)
        if stop is None or stop <= 0:
            return reject(ADD_STOP_DISTANCE_INVALID)
        # §101 — liquidity applies to an ADD exactly as it does to an entry.
        if depth_value is None or depth_value <= 0:
            return reject(ADD_LIQUIDITY_UNKNOWN)
        if margin_value is None or margin_value <= 0:
            return reject(ADD_INSUFFICIENT_MARGIN)

        spec = InstrumentExposureSpec(
            instrument_type=instrument.instrument_type,
            contract_size=D(instrument.contract_size),
            contract_multiplier=D(instrument.contract_multiplier),
        )
        contract_factor = D(instrument.contract_size) * D(instrument.contract_multiplier)
        lot_size = D(instrument.step_size)
        notional_per_unit = ExposureService.calculate(
            quantity=Decimal("1"),
            price=price,
            spec=spec,
            side="LONG" if D(campaign.current_total_qty) >= 0 else "SHORT",
        ).gross_notional
        if contract_factor <= 0 or lot_size <= 0 or notional_per_unit <= 0:
            return reject(ADD_INVALID_SIZING_INPUT)

        # §98 — effective stop distance, floored deterministically.
        minimum_valid = scale_policy.minimum_stop_distance(
            price=price, volatility=volatility
        )
        raw_distance = abs(price - stop)
        effective_distance = max(raw_distance, minimum_valid)
        widened = effective_distance > raw_distance
        if effective_distance <= 0:
            return reject(ADD_STOP_DISTANCE_INVALID)

        bounded_leverage = _clamp_leverage(
            requested=requested_leverage,
            maximum=policy.max_leverage,
            volatility=volatility,
            liquidity=liquidity,
        )

        # §99 — campaign risk left, scaled by conviction/regime/drawdown.
        remaining_campaign_risk = min(
            campaign.remaining_campaign_risk(budget), reserve
        )
        multiplier = conviction_multiplier(conviction)
        risk_budget = (
            remaining_campaign_risk
            * multiplier
            * _unit(regime_multiplier)
            * _unit(drawdown_multiplier)
        )
        risk_quantity = risk_budget / (effective_distance * contract_factor)

        # §84/§105 — remaining capacity up to the CUMULATIVE 5x ceiling.
        position_ceiling = policy.notional_ceiling(equity_value)
        remaining_position_room = position_ceiling - D(campaign.total_notional)
        leverage_cap_quantity = (
            remaining_position_room / notional_per_unit
            if remaining_position_room > 0
            else Decimal("0")
        )
        # §85/§107 — remaining portfolio gross capacity.
        spec_positions = positions or {}
        gross_exposure = (
            ExposureService.for_portfolio(
                spec_positions, prices={instrument.symbol: price}
            ).gross_notional
            if spec_positions
            else D(campaign.total_notional)
        )
        gross_ceiling = policy.gross_ceiling(equity_value)
        remaining_portfolio_room = gross_ceiling - gross_exposure
        portfolio_cap_quantity = (
            remaining_portfolio_room / notional_per_unit
            if remaining_portfolio_room > 0
            else Decimal("0")
        )
        # §106 — margin capacity at the APPROVED leverage.
        margin_cap_quantity = (margin_value * bounded_leverage) / notional_per_unit
        # §101 — factual depth x participation, never relaxed while in position.
        liquidity_cap_quantity = (
            depth_value * policy.max_liquidity_participation
        )
        symbol_cap_quantity = remaining_position_room / notional_per_unit

        candidates = [
            (BINDING_ADD_RISK_BUDGET, risk_quantity),
            (BINDING_LIQUIDITY, liquidity_cap_quantity),
            (BINDING_MARGIN, margin_cap_quantity),
            (BINDING_ADD_PORTFOLIO_CAP, portfolio_cap_quantity),
            (BINDING_ADD_POSITION_CAP, leverage_cap_quantity),
            (BINDING_SYMBOL, symbol_cap_quantity),
        ]
        ordered = _order_candidates(candidates)
        raw_quantity, binding_cap, binding_caps = _minimum_cap(ordered)

        if raw_quantity <= 0:
            reason = (
                ADD_POSITION_CEILING_REACHED
                if leverage_cap_quantity <= 0
                else ADD_PORTFOLIO_CEILING_REACHED
                if portfolio_cap_quantity <= 0
                else ADD_INSUFFICIENT_MARGIN
                if margin_cap_quantity <= 0
                else ADD_LIQUIDITY_UNKNOWN
                if liquidity_cap_quantity <= 0
                else ADD_RISK_BUDGET_EXHAUSTED
            )
            return reject(
                reason,
                risk_budget=risk_budget,
                risk_quantity=risk_quantity,
                leverage_cap_quantity=leverage_cap_quantity,
                portfolio_cap_quantity=portfolio_cap_quantity,
                margin_cap_quantity=margin_cap_quantity,
                liquidity_cap_quantity=liquidity_cap_quantity,
                symbol_cap_quantity=symbol_cap_quantity,
                binding_cap=binding_cap,
                binding_caps=binding_caps,
                effective_stop_distance=effective_distance,
                minimum_valid_stop_distance=minimum_valid,
                stop_distance_was_widened=widened,
                approved_leverage=bounded_leverage,
            )

        final_quantity = floor_to_step(raw_quantity, lot_size)
        if final_quantity <= 0:
            return reject(
                ADD_BELOW_MINIMUM_LOT,
                risk_budget=risk_budget,
                risk_quantity=risk_quantity,
                leverage_cap_quantity=leverage_cap_quantity,
                portfolio_cap_quantity=portfolio_cap_quantity,
                margin_cap_quantity=margin_cap_quantity,
                liquidity_cap_quantity=liquidity_cap_quantity,
                symbol_cap_quantity=symbol_cap_quantity,
                binding_cap=binding_cap,
                binding_caps=binding_caps,
                effective_stop_distance=effective_distance,
                minimum_valid_stop_distance=minimum_valid,
                stop_distance_was_widened=widened,
                approved_leverage=bounded_leverage,
            )

        add_notional = final_quantity * notional_per_unit
        # §100 — no forced upsize to reach the economic minimum.
        min_effective_notional = policy.min_effective_notional(equity_value)
        if add_notional < min_effective_notional:
            return reject(
                ADD_BELOW_ECONOMIC_NOTIONAL,
                risk_budget=risk_budget,
                risk_quantity=risk_quantity,
                leverage_cap_quantity=leverage_cap_quantity,
                portfolio_cap_quantity=portfolio_cap_quantity,
                margin_cap_quantity=margin_cap_quantity,
                liquidity_cap_quantity=liquidity_cap_quantity,
                symbol_cap_quantity=symbol_cap_quantity,
                binding_cap=BINDING_ADD_ECONOMIC_MINIMUM,
                binding_caps=(BINDING_ADD_ECONOMIC_MINIMUM,),
                effective_stop_distance=effective_distance,
                minimum_valid_stop_distance=minimum_valid,
                stop_distance_was_widened=widened,
                approved_leverage=bounded_leverage,
                approved_notional=add_notional,
                approved_quantity=final_quantity,
                notional_pct_of_equity=add_notional / equity_value,
            )

        # §86 — the WHOLE campaign's loss at the (possibly updated) stop.
        added_risk = final_quantity * effective_distance * contract_factor
        projected_risk = D(campaign.total_risk_at_stop) + added_risk
        projection = CampaignProjection(
            add_quantity=final_quantity,
            add_notional=add_notional,
            projected_total_qty=D(campaign.current_total_qty) + final_quantity,
            projected_position_notional=D(campaign.total_notional) + add_notional,
            projected_gross_exposure=gross_exposure + add_notional,
            projected_total_risk_at_stop=projected_risk,
            position_notional_ceiling=position_ceiling,
            gross_exposure_ceiling=gross_ceiling,
            campaign_risk_budget=budget,
            add_number=add_number,
        )
        if projection.projected_position_notional > position_ceiling:
            return reject(
                ADD_POSITION_CEILING_REACHED,
                binding_cap=BINDING_ADD_POSITION_CAP,
                binding_caps=(BINDING_ADD_POSITION_CAP,),
                effective_stop_distance=effective_distance,
                minimum_valid_stop_distance=minimum_valid,
                stop_distance_was_widened=widened,
                approved_leverage=bounded_leverage,
            )
        if projection.projected_gross_exposure > gross_ceiling:
            return reject(
                ADD_PORTFOLIO_CEILING_REACHED,
                binding_cap=BINDING_ADD_PORTFOLIO_CAP,
                binding_caps=(BINDING_ADD_PORTFOLIO_CAP,),
                effective_stop_distance=effective_distance,
                minimum_valid_stop_distance=minimum_valid,
                stop_distance_was_widened=widened,
                approved_leverage=bounded_leverage,
            )
        if not projection.within_campaign_risk:
            return reject(
                ADD_RISK_BUDGET_EXHAUSTED,
                binding_cap=BINDING_ADD_RISK_BUDGET,
                binding_caps=(BINDING_ADD_RISK_BUDGET,),
                projection=projection,
                effective_stop_distance=effective_distance,
                minimum_valid_stop_distance=minimum_valid,
                stop_distance_was_widened=widened,
                approved_leverage=bounded_leverage,
            )

        return ScaleInSize(
            rejected=False,
            approved_quantity=final_quantity,
            approved_notional=add_notional,
            reason_codes=(
                "ADD_RISK_BUDGET",
                "ADD_EFFECTIVE_STOP_DISTANCE",
                "ADD_CUMULATIVE_5X_CAP",
                "ADD_CAMPAIGN_RISK_PASS",
                "ADD_ECONOMIC_NOTIONAL_PASS",
            ),
            binding_cap=binding_cap,
            binding_caps=binding_caps,
            effective_stop_distance=effective_distance,
            minimum_valid_stop_distance=minimum_valid,
            stop_distance_was_widened=widened,
            risk_budget=risk_budget,
            risk_quantity=risk_quantity,
            leverage_cap_quantity=leverage_cap_quantity,
            portfolio_cap_quantity=portfolio_cap_quantity,
            margin_cap_quantity=margin_cap_quantity,
            liquidity_cap_quantity=liquidity_cap_quantity,
            symbol_cap_quantity=symbol_cap_quantity,
            projection=projection,
            equity=equity_value,
            available_margin=margin_value,
            liquidity_depth=depth_value,
            approved_leverage=bounded_leverage,
            max_loss_estimate=added_risk,
            min_effective_notional=min_effective_notional,
            notional_pct_of_equity=add_notional / equity_value,
            add_number=add_number,
        )


def _order_candidates(candidates: list[tuple[str, Decimal]]) -> list[tuple[str, Decimal]]:
    """Deterministically order the cap layers for tie-breaking and reporting."""
    by_name = {name: value for name, value in candidates}
    return [(name, by_name[name]) for name in ADD_CAP_ORDER if name in by_name]


def _minimum_cap(
    candidates: list[tuple[str, Decimal]],
) -> tuple[Decimal, str, tuple[str, ...]]:
    """Smallest cap plus every cap that tied, in the ADD canonical order."""
    best_value: Decimal | None = None
    for _name, value in candidates:
        if best_value is None or value < best_value:
            best_value = value
    if best_value is None:
        return Decimal("0"), BINDING_ADD_NONE, ()
    tied = tuple(name for name, value in candidates if value == best_value)
    primary = tied[0] if tied else BINDING_ADD_NONE
    return best_value, primary, tied


def _clamp_leverage(
    *, requested, maximum, volatility=None, liquidity="1"
) -> Decimal:
    from crypto_trader.risk.leverage import clamp_leverage

    return clamp_leverage(
        requested=requested,
        max_leverage=maximum,
        volatility=volatility if volatility is not None else "0",
        liquidity=liquidity,
    )


def _unit(value) -> Decimal:
    parsed = _finite_or_none(value)
    if parsed is None or parsed <= 0:
        return Decimal("0")
    return parsed


def _finite(value) -> Decimal:
    parsed = _finite_or_none(value)
    return parsed if parsed is not None else Decimal("0")


def _finite_or_none(value) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = D(value)
    except Exception:  # noqa: BLE001 - an unparseable number is not a fact
        return None
    return parsed if parsed.is_finite() else None


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
