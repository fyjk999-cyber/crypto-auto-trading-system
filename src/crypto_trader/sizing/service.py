"""Canonical deterministic sizing contract for Live-LLM entry proposals.

POSITION SIZING V2 — the Sizer OWNS final quantity.

    ChiefTrader  decides WHETHER to take risk (direction / thesis / stop).
    Sizer        decides HOW MUCH risk is appropriate.
    RiskEngine   decides whether that size is LEGALLY SAFE.
    Execution    decides how much the market can actually fill.

The LLM's ``position_size_request`` / ``requested_exposure`` are ADVISORY ONLY
(``LLM_SIZE_ADVISORY_ONLY``): preserved for audit and future calibration, but
they never cap, floor or define the final quantity.

Final quantity is the deterministic minimum of independently computed caps::

    RiskQty         risk-budget derived quantity (stop distance is the risk unit)
    CapitalCapQty   equity x MAX_SINGLE_NOTIONAL_MULTIPLE
    MarginCapQty    available margin x APPROVED (bounded) leverage
    PortfolioCapQty remaining portfolio gross-exposure capacity
    SymbolCapQty    remaining single-symbol capacity
    LiquidityCapQty factual visible depth x MAX_LIQUIDITY_PARTICIPATION
    OrderNotionalQty optional pre-existing static order-notional ceiling

then floored to the instrument lot step, then subjected to the economic
viability gate: a position below ``equity x MIN_EFFECTIVE_NOTIONAL_FRACTION``
is REJECTED, never rounded up (§24).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.domain.money import D, floor_to_step
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.risk.leverage import clamp_leverage
from crypto_trader.sizing.audit import (
    BINDING_ECONOMIC_MINIMUM,
    BINDING_LIQUIDITY,
    BINDING_MARGIN,
    BINDING_NO_BINDING_CAP,
    BINDING_NOTIONAL_CAP,
    BINDING_ORDER_NOTIONAL_LIMIT,
    BINDING_PORTFOLIO,
    BINDING_RISK_BUDGET,
    BINDING_SYMBOL,
    REASON_AVAILABLE_MARGIN_CAP,
    REASON_CAPITAL_5X_CAP,
    REASON_CONVICTION_MULTIPLIER,
    REASON_ECONOMIC_NOTIONAL_PASS,
    REASON_LEVERAGE_CLAMPED,
    REASON_LIQUIDITY_CAP,
    REASON_ORDER_NOTIONAL_LIMIT,
    REASON_PORTFOLIO_GROSS_CAP,
    REASON_RISK_BUDGET,
    REASON_STOP_DISTANCE_RISK_BUDGET,
    REASON_SYMBOL_CAP,
    REJECT_AVAILABLE_MARGIN_UNKNOWN,
    REJECT_BELOW_ECONOMIC_NOTIONAL,
    REJECT_BELOW_MINIMUM_LOT,
    REJECT_INSUFFICIENT_AVAILABLE_MARGIN,
    REJECT_INVALID_SIZING_INPUT,
    REJECT_LIQUIDITY_UNKNOWN,
    REJECT_NO_PORTFOLIO_CAPACITY,
    REJECT_NO_SYMBOL_CAPACITY,
    REJECT_STOP_DISTANCE_UNAVAILABLE,
    REJECT_VALUATION_BATCH_REQUIRED,
    REJECT_VALUATION_BATCH_UNAVAILABLE,
    SizingAudit,
)
from crypto_trader.sizing.conviction import risk_fraction_for_conviction
from crypto_trader.sizing.policy import PositionSizingPolicy
from crypto_trader.valuation.domain import ValuationBatch

#: Canonical cap ordering used for deterministic tie-breaking and reporting.
CAP_ORDER: tuple[str, ...] = (
    BINDING_RISK_BUDGET,
    BINDING_LIQUIDITY,
    BINDING_MARGIN,
    BINDING_PORTFOLIO,
    BINDING_SYMBOL,
    BINDING_NOTIONAL_CAP,
    BINDING_ORDER_NOTIONAL_LIMIT,
)

#: Reason code attached to whichever cap layer was at or below the risk budget.
CAP_REASON_CODES: dict[str, str] = {
    BINDING_NOTIONAL_CAP: REASON_CAPITAL_5X_CAP,
    BINDING_MARGIN: REASON_AVAILABLE_MARGIN_CAP,
    BINDING_PORTFOLIO: REASON_PORTFOLIO_GROSS_CAP,
    BINDING_SYMBOL: REASON_SYMBOL_CAP,
    BINDING_LIQUIDITY: REASON_LIQUIDITY_CAP,
    BINDING_ORDER_NOTIONAL_LIMIT: REASON_ORDER_NOTIONAL_LIMIT,
}


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
    valuation_id: str | None = None
    sizing_equity: Decimal | None = None
    available_margin: Decimal | None = None
    # --- Position Sizing V2 ------------------------------------------------
    binding_cap: str = BINDING_NO_BINDING_CAP
    binding_caps: tuple[str, ...] = ()
    rejected: bool = False
    symbol_exposure_after_trade: Decimal = Decimal("0")
    audit: SizingAudit | None = None

    @property
    def final_quantity(self) -> Decimal:
        """The one quantity the Sizer authorises (Execution may fill less)."""
        return self.normalized_quantity

    @property
    def final_notional(self) -> Decimal:
        return self.risk_normalized_notional


@dataclass(frozen=True)
class _Request:
    """Normalised, already-validated entry request plus its audit scaffolding."""

    side: str
    price: Decimal
    stop_price: Decimal | None
    stop_distance: Decimal
    requested_quantity: Decimal
    requested_exposure: Decimal | None
    requested_leverage: Decimal
    conviction: Decimal
    liquidity_depth_qty: Decimal | None
    valuation: ValuationBatch | None
    #: Set when the caller SUPPLIED a stop that is not a usable factual number
    #: (non-finite). It is never silently rewritten into a different price.
    stop_unusable: bool = False

    @property
    def equity(self) -> Decimal | None:
        """Proven equity, or None when the batch holds no usable fact."""
        if self.valuation is None:
            return None
        return _finite_decimal(self.valuation.raw_mtm_equity)

    @property
    def available_margin(self) -> Decimal | None:
        if self.valuation is None:
            return None
        return _finite_decimal(self.valuation.available_margin)

    @property
    def liquidity_depth(self) -> Decimal | None:
        return _finite_decimal(self.liquidity_depth_qty)


class LiveEntrySizingService:
    """Deterministic capital-aware position sizer.

    Authority: quantity only.  This service never selects a direction, never
    picks a symbol, never rewrites a thesis or a stop, and never raises a size
    to satisfy a minimum.
    """

    def __init__(
        self,
        *,
        policy: PositionSizingPolicy | None = None,
        risk_fraction: Decimal | None = None,
        max_order_notional: Decimal | None = None,
        max_leverage: Decimal | None = None,
    ) -> None:
        updates: dict = dict(dataclasses.asdict(policy)) if policy is not None else {}
        # Legacy keyword compatibility: ``risk_fraction`` was the single risk
        # budget input and now seeds the base risk per trade.
        if risk_fraction is not None:
            updates["base_risk_per_trade"] = D(risk_fraction)
        if max_order_notional is not None:
            updates["static_max_order_notional"] = D(max_order_notional)
        if max_leverage is not None:
            updates["max_leverage"] = D(max_leverage)
        self.policy = PositionSizingPolicy(**updates) if updates else PositionSizingPolicy()

    # ------------------------------------------------------------------ public
    def size(
        self,
        *,
        side: str,
        requested_leverage: Decimal,
        account: Account,
        positions: dict[str, Position],
        instrument: Instrument,
        price: Decimal,
        stop_price: Decimal | None,
        liquidity_depth_qty: Decimal | None,
        requested_quantity: Decimal = Decimal("0"),
        requested_exposure: Decimal | None = None,
        conviction: Decimal = Decimal("0"),
        volatility: Decimal = Decimal("0"),
        liquidity: Decimal = Decimal("1"),
        valuation: ValuationBatch | None = None,
    ) -> CanonicalSize:
        """Compute the authoritative entry quantity.

        ``liquidity_depth_qty`` is the FACTUAL visible depth on the side the
        order would consume (asks for LONG, bids for SHORT).  ``None`` means
        UNKNOWN and fails closed — liquidity is never assumed infinite (§22).

        ``requested_quantity`` / ``requested_exposure`` are the LLM's advisory
        numbers: recorded, never enforced (§6, §32).
        """
        policy = self.policy
        price_value = _safe_decimal(price)
        # A supplied stop that is not a finite number is UNUSABLE — it is never
        # rewritten into some other price (a non-finite stop must fail closed,
        # not silently become a stop at 0 or at infinity).
        stop_price_value = None
        stop_unusable = False
        if stop_price is not None:
            stop_price_value = _finite_decimal(stop_price)
            if stop_price_value is None:
                stop_unusable = True
        request = _Request(
            side=str(side).upper(),
            price=price_value,
            stop_price=stop_price_value,
            stop_distance=(
                abs(price_value - stop_price_value)
                if stop_price_value is not None
                else Decimal("0")
            ),
            requested_quantity=_safe_decimal(requested_quantity),
            requested_exposure=(
                _safe_decimal(requested_exposure)
                if requested_exposure is not None
                else None
            ),
            requested_leverage=_safe_decimal(requested_leverage or "1"),
            conviction=conviction,
            liquidity_depth_qty=liquidity_depth_qty,
            valuation=valuation,
            stop_unusable=stop_unusable,
        )

        # ------------------------------------------- fail-closed entry guards
        # Each of these means the request cannot be honestly sized.  The audit
        # records the facts that ARE known and invents nothing.
        guard_failure = _guard_failure(request)
        if guard_failure is not None:
            return self._reject_unavailable(guard_failure, request=request)

        equity = request.equity
        assert equity is not None  # guaranteed by _guard_failure
        available_margin = request.available_margin
        assert available_margin is not None
        liquidity_depth = request.liquidity_depth
        assert liquidity_depth is not None

        spec = InstrumentExposureSpec(
            instrument_type=instrument.instrument_type,
            contract_size=D(instrument.contract_size),
            contract_multiplier=D(instrument.contract_multiplier),
        )
        contract_factor = D(instrument.contract_size) * D(instrument.contract_multiplier)
        lot_size = D(instrument.step_size)
        notional_per_unit = ExposureService.calculate(
            quantity=Decimal("1"), price=request.price, spec=spec, side=request.side
        ).gross_notional
        if contract_factor <= 0 or lot_size <= 0 or notional_per_unit <= 0:
            return self._reject_unavailable(
                REJECT_INVALID_SIZING_INPUT, request=request
            )

        # ---------------------------- leverage must be bounded BEFORE margin.
        # Margin capacity is AvailableMargin x APPROVED leverage, never
        # AvailableMargin x max_leverage (§16).
        bounded_leverage = clamp_leverage(
            requested=request.requested_leverage,
            max_leverage=policy.max_leverage,
            volatility=volatility,
            liquidity=liquidity,
        )
        leverage_clamped = bounded_leverage < request.requested_leverage

        # ----------------------------------------------- risk budget (§7-§9)
        fraction = risk_fraction_for_conviction(
            confidence=request.conviction,
            base_risk_per_trade=policy.base_risk_per_trade,
            max_risk_per_trade=policy.max_risk_per_trade,
            min_risk_per_trade=policy.min_risk_per_trade,
        )
        risk_budget = equity * fraction.effective_fraction

        # --------------------------------- independent cap layers (§10, §12-§21)
        risk_qty = risk_budget / (request.stop_distance * contract_factor)
        capital_cap_qty = policy.notional_ceiling(equity) / notional_per_unit
        margin_cap_qty = (available_margin * bounded_leverage) / notional_per_unit

        existing_exposure = ExposureService.for_portfolio(
            positions, prices={instrument.symbol: request.price}
        ).gross_notional
        current = positions.get(instrument.symbol)
        existing_symbol_exposure = (
            ExposureService.for_position(current, price=request.price).gross_notional
            if current is not None
            else Decimal("0")
        )
        portfolio_cap_qty = max(
            policy.gross_ceiling(equity) - existing_exposure, Decimal("0")
        ) / notional_per_unit
        symbol_cap_qty = max(
            policy.symbol_ceiling(equity) - existing_symbol_exposure, Decimal("0")
        ) / notional_per_unit
        liquidity_cap_qty = liquidity_depth * policy.max_liquidity_participation

        candidates: list[tuple[str, Decimal]] = [
            (BINDING_RISK_BUDGET, risk_qty),
            (BINDING_LIQUIDITY, liquidity_cap_qty),
            (BINDING_MARGIN, margin_cap_qty),
            (BINDING_PORTFOLIO, portfolio_cap_qty),
            (BINDING_SYMBOL, symbol_cap_qty),
            (BINDING_NOTIONAL_CAP, capital_cap_qty),
        ]
        if policy.static_max_order_notional is not None:
            candidates.append(
                (
                    BINDING_ORDER_NOTIONAL_LIMIT,
                    policy.static_max_order_notional / notional_per_unit,
                )
            )
        order_notional_cap_qty = next(
            (qty for name, qty in candidates if name == BINDING_ORDER_NOTIONAL_LIMIT),
            None,
        )

        def caps_audit(
            *,
            final_qty: Decimal,
            final_notional: Decimal,
            max_loss: Decimal,
            binding_cap: str,
            binding_caps: tuple[str, ...] = (),
            extra_reasons: tuple[str, ...] = (),
        ) -> dict:
            return _audit_kwargs(
                policy=policy,
                request=request,
                equity=equity,
                fraction=fraction,
                risk_budget=risk_budget,
                notional_per_unit=notional_per_unit,
                risk_qty=risk_qty,
                capital_cap_qty=capital_cap_qty,
                margin_cap_qty=margin_cap_qty,
                portfolio_cap_qty=portfolio_cap_qty,
                symbol_cap_qty=symbol_cap_qty,
                liquidity_cap_qty=liquidity_cap_qty,
                order_notional_cap_qty=order_notional_cap_qty,
                final_qty=final_qty,
                final_notional=final_notional,
                max_loss=max_loss,
                approved_leverage=bounded_leverage,
                existing_exposure=existing_exposure,
                existing_symbol_exposure=existing_symbol_exposure,
                liquidity_depth=liquidity_depth,
                binding_cap=binding_cap,
                binding_caps=binding_caps,
                extra_reasons=extra_reasons,
            )

        def reject_caps(reason: str, audit_kwargs: dict) -> CanonicalSize:
            return self._reject_with_caps(
                reason,
                audit_kwargs=audit_kwargs,
                request=request,
                approved_leverage=bounded_leverage,
                equity=equity,
                available_margin=available_margin,
                existing_symbol_exposure=existing_symbol_exposure,
            )

        raw_quantity, binding_cap, binding_caps = _minimum_cap(candidates)
        if raw_quantity <= 0:
            return reject_caps(
                _zero_capacity_reason(candidates),
                caps_audit(
                    final_qty=Decimal("0"),
                    final_notional=Decimal("0"),
                    max_loss=Decimal("0"),
                    binding_cap=BINDING_NO_BINDING_CAP,
                ),
            )

        final_quantity = floor_to_step(raw_quantity, lot_size)
        if final_quantity <= 0:
            return reject_caps(
                REJECT_BELOW_MINIMUM_LOT,
                caps_audit(
                    final_qty=Decimal("0"),
                    final_notional=Decimal("0"),
                    max_loss=Decimal("0"),
                    binding_cap=binding_cap,
                    binding_caps=binding_caps,
                ),
            )

        # §11: lot rounding may only ever REDUCE risk, never increase it.
        max_loss = final_quantity * request.stop_distance * contract_factor
        if max_loss > risk_budget:
            final_quantity = floor_to_step(
                risk_budget / (request.stop_distance * contract_factor), lot_size
            )
            if final_quantity <= 0:
                return reject_caps(
                    REJECT_BELOW_MINIMUM_LOT,
                    caps_audit(
                        final_qty=Decimal("0"),
                        final_notional=Decimal("0"),
                        max_loss=Decimal("0"),
                        binding_cap=BINDING_RISK_BUDGET,
                    ),
                )
            max_loss = final_quantity * request.stop_distance * contract_factor
            binding_cap = BINDING_RISK_BUDGET
            binding_caps = (BINDING_RISK_BUDGET,)

        final_notional = final_quantity * notional_per_unit

        # ----------------------------- complete reason chain (§30), not just one
        reasons: list[str] = [REASON_RISK_BUDGET, REASON_STOP_DISTANCE_RISK_BUDGET]
        if fraction.multiplier != Decimal("1"):
            reasons.append(REASON_CONVICTION_MULTIPLIER)
        if leverage_clamped:
            reasons.append(REASON_LEVERAGE_CLAMPED)
        for name, value in candidates:
            reason = CAP_REASON_CODES.get(name)
            if reason is not None and value <= risk_qty:
                reasons.append(reason)
        binding_reason = CAP_REASON_CODES.get(binding_cap)
        if binding_reason is not None:
            reasons.append(binding_reason)

        # -------------------------------- economic viability gate (§23, §24)
        min_effective_notional = policy.min_effective_notional(equity)
        if final_notional < min_effective_notional:
            return reject_caps(
                REJECT_BELOW_ECONOMIC_NOTIONAL,
                caps_audit(
                    final_qty=final_quantity,
                    final_notional=final_notional,
                    max_loss=max_loss,
                    binding_cap=BINDING_ECONOMIC_MINIMUM,
                    binding_caps=(BINDING_ECONOMIC_MINIMUM,),
                    extra_reasons=tuple(reasons),
                ),
            )
        reasons.append(REASON_ECONOMIC_NOTIONAL_PASS)

        audit = SizingAudit(
            **caps_audit(
                final_qty=final_quantity,
                final_notional=final_notional,
                max_loss=max_loss,
                binding_cap=binding_cap,
                binding_caps=binding_caps,
                extra_reasons=tuple(reasons),
            )
        )
        return CanonicalSize(
            requested_notional=audit.llm_requested_exposure,
            risk_normalized_notional=final_notional,
            normalized_quantity=final_quantity,
            requested_leverage=request.requested_leverage,
            risk_bounded_leverage=bounded_leverage,
            max_loss_estimate=max_loss,
            portfolio_exposure_after_trade=existing_exposure + final_notional,
            sizing_reason_codes=audit.sizing_reason_codes,
            valuation_id=request.valuation.valuation_id if request.valuation else None,
            sizing_equity=equity,
            available_margin=available_margin,
            binding_cap=binding_cap,
            binding_caps=binding_caps,
            rejected=False,
            symbol_exposure_after_trade=existing_symbol_exposure + final_notional,
            audit=audit,
        )

    # ------------------------------------------------------------- rejections
    def _reject_unavailable(self, reason: str, *, request: _Request) -> CanonicalSize:
        """Fail closed before cap math is meaningful; invent nothing."""
        policy = self.policy
        audit = SizingAudit(
            **{
                **_audit_kwargs(
                    policy=policy,
                    request=request,
                    equity=request.equity,
                    fraction=_fraction_for(policy, request.conviction),
                    risk_budget=Decimal("0"),
                    notional_per_unit=Decimal("0"),
                    risk_qty=Decimal("0"),
                    capital_cap_qty=Decimal("0"),
                    margin_cap_qty=Decimal("0"),
                    portfolio_cap_qty=Decimal("0"),
                    symbol_cap_qty=Decimal("0"),
                    liquidity_cap_qty=Decimal("0"),
                    order_notional_cap_qty=None,
                    final_qty=Decimal("0"),
                    final_notional=Decimal("0"),
                    max_loss=Decimal("0"),
                    approved_leverage=Decimal("0"),
                    existing_exposure=Decimal("0"),
                    existing_symbol_exposure=Decimal("0"),
                    liquidity_depth=request.liquidity_depth,
                    binding_cap=BINDING_NO_BINDING_CAP,
                ),
                "sizing_reason_codes": tuple(
                    dict.fromkeys((*policy.reason_codes, reason))
                ),
            }
        )
        return CanonicalSize(
            requested_notional=audit.llm_requested_exposure,
            risk_normalized_notional=Decimal("0"),
            normalized_quantity=Decimal("0"),
            requested_leverage=request.requested_leverage,
            risk_bounded_leverage=Decimal("0"),
            max_loss_estimate=Decimal("0"),
            portfolio_exposure_after_trade=Decimal("0"),
            sizing_reason_codes=audit.sizing_reason_codes,
            valuation_id=audit.valuation_id,
            sizing_equity=request.equity,
            available_margin=request.available_margin,
            binding_cap=BINDING_NO_BINDING_CAP,
            binding_caps=(),
            rejected=True,
            symbol_exposure_after_trade=Decimal("0"),
            audit=audit,
        )

    def _reject_with_caps(
        self,
        reason: str,
        *,
        audit_kwargs: dict,
        request: _Request,
        approved_leverage: Decimal,
        equity: Decimal,
        available_margin: Decimal,
        existing_symbol_exposure: Decimal,
    ) -> CanonicalSize:
        """Reject while KEEPING the full cap math — rejections stay explainable."""
        audit = SizingAudit(
            **{
                **audit_kwargs,
                "sizing_reason_codes": tuple(
                    dict.fromkeys((*audit_kwargs["sizing_reason_codes"], reason))
                ),
            }
        )
        return CanonicalSize(
            requested_notional=audit.llm_requested_exposure,
            risk_normalized_notional=Decimal("0"),
            normalized_quantity=Decimal("0"),
            requested_leverage=request.requested_leverage,
            risk_bounded_leverage=approved_leverage,
            max_loss_estimate=Decimal("0"),
            portfolio_exposure_after_trade=audit.existing_gross_exposure,
            sizing_reason_codes=audit.sizing_reason_codes,
            valuation_id=audit.valuation_id,
            sizing_equity=equity,
            available_margin=available_margin,
            binding_cap=audit.binding_cap,
            binding_caps=audit.binding_caps,
            rejected=True,
            symbol_exposure_after_trade=existing_symbol_exposure,
            audit=audit,
        )


def _guard_failure(request: _Request) -> str | None:
    """The first reason this request cannot be honestly sized; else None."""
    if request.side not in {"LONG", "SHORT"} or request.price <= 0:
        return REJECT_INVALID_SIZING_INPUT
    if request.valuation is None:
        # §28: sizing equity must come from a proven ValuationBatch, never from
        # stale ledger cash or a hardcoded fallback equity.
        return REJECT_VALUATION_BATCH_REQUIRED
    if not request.valuation.usable_for_new_risk:
        return REJECT_VALUATION_BATCH_UNAVAILABLE
    if request.equity is None or request.equity <= 0:
        # Covers a non-finite equity (NaN/Infinity is not a factual balance).
        return REJECT_INVALID_SIZING_INPUT
    # §29: available margin must be factual.  UNKNOWN (absent or non-finite) is
    # never guessed.
    if request.available_margin is None:
        return REJECT_AVAILABLE_MARGIN_UNKNOWN
    if request.available_margin <= 0:
        return REJECT_INSUFFICIENT_AVAILABLE_MARGIN
    if request.stop_unusable or request.stop_distance <= 0:
        # No usable stop distance means no risk unit and no honest
        # risk-normalised quantity.  Never treat the whole price as risk, and
        # never substitute a fabricated stop price.
        return REJECT_STOP_DISTANCE_UNAVAILABLE
    # §22: no factual depth (missing or non-positive) is UNKNOWN and must never
    # be replaced by an assumption of infinite liquidity.
    if request.liquidity_depth is None or request.liquidity_depth <= 0:
        return REJECT_LIQUIDITY_UNKNOWN
    return None


def _fraction_for(policy: PositionSizingPolicy, conviction):
    return risk_fraction_for_conviction(
        confidence=conviction,
        base_risk_per_trade=policy.base_risk_per_trade,
        max_risk_per_trade=policy.max_risk_per_trade,
        min_risk_per_trade=policy.min_risk_per_trade,
    )


def _audit_kwargs(
    *,
    policy: PositionSizingPolicy,
    request: _Request,
    equity: Decimal | None,
    fraction,
    risk_budget: Decimal,
    notional_per_unit: Decimal,
    risk_qty: Decimal,
    capital_cap_qty: Decimal,
    margin_cap_qty: Decimal,
    portfolio_cap_qty: Decimal,
    symbol_cap_qty: Decimal,
    liquidity_cap_qty: Decimal,
    order_notional_cap_qty: Decimal | None,
    final_qty: Decimal,
    final_notional: Decimal,
    max_loss: Decimal,
    approved_leverage: Decimal,
    existing_exposure: Decimal,
    existing_symbol_exposure: Decimal,
    liquidity_depth: Decimal | None,
    binding_cap: str,
    binding_caps: tuple[str, ...] = (),
    extra_reasons: tuple[str, ...] = (),
) -> dict:
    llm_exposure = (
        request.requested_exposure
        if request.requested_exposure is not None and request.requested_exposure > 0
        else (max(request.requested_quantity, Decimal("0")) * notional_per_unit)
    )
    return {
        "equity": equity,
        "valuation_id": (
            request.valuation.valuation_id if request.valuation is not None else None
        ),
        "valuation_quality": (
            request.valuation.quality if request.valuation is not None else None
        ),
        "entry_price": request.price,
        "stop_price": request.stop_price,
        "stop_distance": request.stop_distance,
        "stop_distance_pct": (
            (request.stop_distance / request.price) if request.price > 0 else Decimal("0")
        ),
        "base_risk_fraction": policy.base_risk_per_trade,
        "conviction": fraction.conviction,
        "conviction_multiplier": fraction.multiplier,
        "effective_risk_fraction": fraction.effective_fraction,
        "risk_budget": risk_budget,
        "llm_requested_quantity": request.requested_quantity,
        "llm_requested_exposure": llm_exposure,
        "risk_qty": risk_qty,
        "capital_cap_qty": capital_cap_qty,
        "margin_cap_qty": margin_cap_qty,
        "portfolio_cap_qty": portfolio_cap_qty,
        "symbol_cap_qty": symbol_cap_qty,
        "liquidity_cap_qty": liquidity_cap_qty,
        "order_notional_cap_qty": order_notional_cap_qty,
        "final_qty": final_qty,
        "final_notional": final_notional,
        "max_loss_estimate": max_loss,
        "requested_leverage": request.requested_leverage,
        "approved_leverage": approved_leverage,
        "available_margin": request.available_margin,
        "existing_gross_exposure": existing_exposure,
        "existing_symbol_exposure": existing_symbol_exposure,
        "portfolio_exposure_after_trade": existing_exposure + final_notional,
        "symbol_exposure_after_trade": existing_symbol_exposure + final_notional,
        "liquidity_depth": liquidity_depth,
        "liquidity_participation": policy.max_liquidity_participation,
        "binding_cap": binding_cap,
        "binding_caps": tuple(binding_caps),
        "notional_pct_of_equity": (
            (final_notional / equity) if equity is not None and equity > 0 else None
        ),
        "min_effective_notional": (
            policy.min_effective_notional(equity) if equity is not None else None
        ),
        "sizing_reason_codes": tuple(
            dict.fromkeys((*policy.reason_codes, *extra_reasons))
        ),
        "policy": policy.to_evidence(),
    }


def _minimum_cap(
    candidates: list[tuple[str, Decimal]],
) -> tuple[Decimal, str, tuple[str, ...]]:
    """Smallest cap, with a deterministic canonical tie-break (§62).

    Returns ``(value, primary_cap, all_tied_caps)``. Reporting every tied cap
    keeps the explanation honest: with ``available_margin == equity`` at 5x,
    the margin cap and the 5x-equity cap genuinely coincide, and naming only
    one of them would hide a real constraint.
    """
    best_value: Decimal | None = None
    for _name, value in candidates:
        if best_value is None or value < best_value:
            best_value = value
    if best_value is None:
        return Decimal("0"), BINDING_NO_BINDING_CAP, ()
    tied = tuple(
        name
        for name in CAP_ORDER
        if any(
            candidate_name == name and value == best_value
            for candidate_name, value in candidates
        )
    )
    primary = tied[0] if tied else BINDING_NO_BINDING_CAP
    return best_value, primary, tied


def _zero_capacity_reason(candidates: list[tuple[str, Decimal]]) -> str:
    zero_names = {name for name, value in candidates if value <= 0}
    for name, reason in (
        (BINDING_PORTFOLIO, REJECT_NO_PORTFOLIO_CAPACITY),
        (BINDING_SYMBOL, REJECT_NO_SYMBOL_CAPACITY),
        (BINDING_LIQUIDITY, REJECT_LIQUIDITY_UNKNOWN),
        (BINDING_MARGIN, REJECT_INSUFFICIENT_AVAILABLE_MARGIN),
    ):
        if name in zero_names:
            return reason
    return REJECT_BELOW_MINIMUM_LOT


def _safe_decimal(value) -> Decimal:
    """Parse a number; anything unusable degrades to 0.

    ``0`` is the strictest reading for every field this is used on (price,
    equity, depth, quantities), because each of those has a zero-based
    rejection guard. Documented here so the choice is deliberate, not implicit.
    """
    if value is None:
        return Decimal("0")
    try:
        parsed = D(value)
    except Exception:  # noqa: BLE001 - an unparseable number is not a fact
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def _finite_decimal(value) -> Decimal | None:
    """Parse a number that must be a real fact; UNKNOWN returns ``None``.

    Used where ``0`` would be a *different meaningful value* rather than a
    rejection (stop price, equity, margin, liquidity depth). A NaN/Infinity
    here means the fact is absent, so callers must fail closed instead of
    silently substituting a different price or balance.
    """
    if value is None:
        return None
    try:
        parsed = D(value)
    except Exception:  # noqa: BLE001 - an unparseable number is not a fact
        return None
    return parsed if parsed.is_finite() else None
