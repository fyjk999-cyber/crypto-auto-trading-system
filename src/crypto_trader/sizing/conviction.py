"""Deterministic conviction -> risk-budget mapping.

Conviction is the ONLY way an LLM signal can influence position size, and it
influences the RISK BUDGET only:

    RiskFraction = clamp(base_risk_per_trade x conviction_multiplier,
                         min_risk_per_trade,
                         max_risk_per_trade)

It can never produce leverage directly (``confidence x 5`` is forbidden), can
never exceed ``max_risk_per_trade``, and a lower conviction can never produce a
larger risk budget than a higher one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.sizing.policy import HARD_MAX_RISK_PER_TRADE

#: ``(lower_bound, multiplier)`` sorted DESCENDING.  The first band whose lower
#: bound is satisfied wins, so the mapping is total and deterministic.
CONVICTION_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.92"), Decimal("1.40")),
    (Decimal("0.85"), Decimal("1.20")),
    (Decimal("0.75"), Decimal("1.00")),
    (Decimal("0.65"), Decimal("0.80")),
    (Decimal("0.55"), Decimal("0.65")),
)

#: Applied when conviction is below the lowest band.
CONVICTION_MULTIPLIER_FLOOR = Decimal("0.50")


@dataclass(frozen=True)
class RiskFractionDecision:
    """Auditable result of the conviction -> risk-fraction mapping."""

    conviction: Decimal
    multiplier: Decimal
    raw_fraction: Decimal
    effective_fraction: Decimal

    @property
    def clamped(self) -> bool:
        return self.raw_fraction != self.effective_fraction


def conviction_multiplier(confidence) -> Decimal:
    """Bounded, deterministic, monotone non-decreasing band mapping (§8)."""
    value = _bounded_confidence(confidence)
    for lower, multiplier in CONVICTION_BANDS:
        if value >= lower:
            return multiplier
    return CONVICTION_MULTIPLIER_FLOOR


def risk_fraction_for_conviction(
    *,
    confidence,
    base_risk_per_trade,
    max_risk_per_trade,
    min_risk_per_trade=Decimal("0"),
) -> RiskFractionDecision:
    """Effective risk fraction for one entry, always within the hard ceiling.

    The caller's ``max_risk_per_trade`` is itself clamped against the project
    hard ceiling, so this function is safe even when called directly with an
    unclamped value: no conviction level can ever exceed 1% of equity (§8).
    """
    conviction = _bounded_confidence(confidence)
    multiplier = conviction_multiplier(conviction)
    raw = D(base_risk_per_trade) * multiplier

    # The floor may never raise risk above the ceiling: when a caller asks for a
    # floor higher than the ceiling, the CEILING wins. This keeps the "<= 1% of
    # equity, whatever the conviction" guarantee true for direct callers too.
    upper = min(D(max_risk_per_trade), HARD_MAX_RISK_PER_TRADE)
    lower = min(max(D(min_risk_per_trade), Decimal("0")), upper)
    effective = min(max(raw, lower), upper)
    return RiskFractionDecision(
        conviction=conviction,
        multiplier=multiplier,
        raw_fraction=raw,
        effective_fraction=effective,
    )


def _bounded_confidence(confidence) -> Decimal:
    """Confidence is a [0, 1] ratio; anything else degrades to 0 (lowest band)."""
    if confidence is None:
        return Decimal("0")
    try:
        value = D(confidence)
    except Exception:  # noqa: BLE001 - unparseable confidence is not a fact
        return Decimal("0")
    if not value.is_finite() or value < 0:
        return Decimal("0")
    if value > 1:
        return Decimal("1")
    return value
