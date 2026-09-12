"""Durable sizing audit: every ENTRY must be explainable after the fact.

Requirement (§63, "no mystery positions"): given a filled order, it must be
possible to reconstruct WHY the quantity was exactly that number — equity,
risk budget, stop distance, every cap layer, and the final binding cap.

The LLM's raw quantity/exposure is preserved here for analysis even though it
holds no authority (§32).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.money import D

# Binding-cap taxonomy (§62).
BINDING_RISK_BUDGET = "RISK_BUDGET"
BINDING_LIQUIDITY = "LIQUIDITY"
BINDING_MARGIN = "MARGIN"
BINDING_PORTFOLIO = "PORTFOLIO"
BINDING_SYMBOL = "SYMBOL"
BINDING_NOTIONAL_CAP = "5X_CAP"
BINDING_ORDER_NOTIONAL_LIMIT = "ORDER_NOTIONAL_LIMIT"
BINDING_ECONOMIC_MINIMUM = "ECONOMIC_MINIMUM"
BINDING_NO_BINDING_CAP = "NONE"

# Reason codes (§30).
REASON_RISK_BUDGET = "RISK_BUDGET"
REASON_CONVICTION_MULTIPLIER = "CONVICTION_MULTIPLIER"
REASON_STOP_DISTANCE_RISK_BUDGET = "STOP_DISTANCE_RISK_BUDGET"
REASON_CAPITAL_5X_CAP = "CAPITAL_5X_CAP"
REASON_AVAILABLE_MARGIN_CAP = "AVAILABLE_MARGIN_CAP"
REASON_PORTFOLIO_GROSS_CAP = "PORTFOLIO_GROSS_CAP"
REASON_SYMBOL_CAP = "SYMBOL_CAP"
REASON_LIQUIDITY_CAP = "LIQUIDITY_CAP"
REASON_LEVERAGE_CLAMPED = "LEVERAGE_CLAMPED"
REASON_ECONOMIC_NOTIONAL_PASS = "ECONOMIC_NOTIONAL_PASS"
REASON_ECONOMIC_NOTIONAL_REJECT = "BELOW_ECONOMIC_NOTIONAL"
REASON_ORDER_NOTIONAL_LIMIT = "ORDER_NOTIONAL_LIMIT"

# Rejection codes (fail-closed).
REJECT_VALUATION_BATCH_REQUIRED = "VALUATION_BATCH_REQUIRED"
REJECT_VALUATION_BATCH_UNAVAILABLE = "VALUATION_BATCH_UNAVAILABLE"
REJECT_AVAILABLE_MARGIN_UNKNOWN = "AVAILABLE_MARGIN_UNKNOWN"
REJECT_INSUFFICIENT_AVAILABLE_MARGIN = "INSUFFICIENT_AVAILABLE_MARGIN"
REJECT_LIQUIDITY_UNKNOWN = "LIQUIDITY_UNKNOWN"
REJECT_INVALID_SIZING_INPUT = "INVALID_SIZING_INPUT"
REJECT_STOP_DISTANCE_UNAVAILABLE = "STOP_DISTANCE_UNAVAILABLE"
REJECT_BELOW_MINIMUM_LOT = "BELOW_MINIMUM_LOT"
REJECT_BELOW_ECONOMIC_NOTIONAL = "BELOW_ECONOMIC_NOTIONAL"
REJECT_NO_PORTFOLIO_CAPACITY = "NO_PORTFOLIO_GROSS_CAPACITY"
REJECT_NO_SYMBOL_CAPACITY = "NO_SYMBOL_CAPACITY"


@dataclass(frozen=True)
class SizingAudit:
    """Complete, JSON-serialisable explanation of one sizing decision."""

    equity: Decimal | None
    valuation_id: str | None
    valuation_quality: str | None

    entry_price: Decimal
    stop_price: Decimal | None
    stop_distance: Decimal
    stop_distance_pct: Decimal

    base_risk_fraction: Decimal
    conviction: Decimal
    conviction_multiplier: Decimal
    effective_risk_fraction: Decimal
    risk_budget: Decimal

    llm_requested_quantity: Decimal
    llm_requested_exposure: Decimal

    risk_qty: Decimal
    capital_cap_qty: Decimal
    margin_cap_qty: Decimal
    portfolio_cap_qty: Decimal
    symbol_cap_qty: Decimal
    liquidity_cap_qty: Decimal
    order_notional_cap_qty: Decimal | None

    final_qty: Decimal
    final_notional: Decimal
    max_loss_estimate: Decimal

    requested_leverage: Decimal
    approved_leverage: Decimal

    available_margin: Decimal | None
    existing_gross_exposure: Decimal
    existing_symbol_exposure: Decimal
    portfolio_exposure_after_trade: Decimal
    symbol_exposure_after_trade: Decimal

    liquidity_depth: Decimal | None
    liquidity_participation: Decimal

    binding_cap: str
    notional_pct_of_equity: Decimal | None
    min_effective_notional: Decimal | None

    #: Every cap that bound the final quantity. ``binding_cap`` is the first of
    #: these in the canonical order; the extra names make ties honest (with
    #: ``available_margin == equity`` at 5x, MARGIN and 5X_CAP genuinely tie).
    binding_caps: tuple[str, ...] = field(default=())
    sizing_reason_codes: tuple[str, ...] = field(default=())
    policy: dict = field(default_factory=dict)

    def to_evidence(self) -> dict:
        """Durable form: every Decimal as a string, tuple as a list."""
        return {
            "equity": _s(self.equity),
            "valuation_id": self.valuation_id,
            "valuation_quality": self.valuation_quality,
            "entry_price": _s(self.entry_price),
            "stop_price": _s(self.stop_price),
            "stop_distance": _s(self.stop_distance),
            "stop_distance_pct": _s(self.stop_distance_pct),
            "base_risk_fraction": _s(self.base_risk_fraction),
            "conviction": _s(self.conviction),
            "conviction_multiplier": _s(self.conviction_multiplier),
            "effective_risk_fraction": _s(self.effective_risk_fraction),
            "risk_budget": _s(self.risk_budget),
            "requested_quantity_from_llm": _s(self.llm_requested_quantity),
            "requested_exposure_from_llm": _s(self.llm_requested_exposure),
            "risk_qty": _s(self.risk_qty),
            "capital_cap_qty": _s(self.capital_cap_qty),
            "margin_cap_qty": _s(self.margin_cap_qty),
            "portfolio_cap_qty": _s(self.portfolio_cap_qty),
            "symbol_cap_qty": _s(self.symbol_cap_qty),
            "liquidity_cap_qty": _s(self.liquidity_cap_qty),
            "order_notional_cap_qty": _s(self.order_notional_cap_qty),
            "final_qty": _s(self.final_qty),
            "final_notional": _s(self.final_notional),
            "requested_leverage": _s(self.requested_leverage),
            "approved_leverage": _s(self.approved_leverage),
            "max_loss_estimate": _s(self.max_loss_estimate),
            "available_margin": _s(self.available_margin),
            "existing_gross_exposure": _s(self.existing_gross_exposure),
            "existing_symbol_exposure": _s(self.existing_symbol_exposure),
            "portfolio_exposure_after_trade": _s(self.portfolio_exposure_after_trade),
            "symbol_exposure_after_trade": _s(self.symbol_exposure_after_trade),
            "liquidity_depth": _s(self.liquidity_depth),
            "liquidity_participation": _s(self.liquidity_participation),
            "binding_cap": self.binding_cap,
            "binding_caps": list(self.binding_caps),
            "notional_pct_of_equity": _s(self.notional_pct_of_equity),
            "min_effective_notional": _s(self.min_effective_notional),
            "sizing_reason_codes": list(self.sizing_reason_codes),
            "policy": self.policy,
        }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(D(value))
