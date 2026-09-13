"""Canonical deterministic sizing for Live-LLM entry proposals.

POSITION SIZING V2 authority model:

    ChiefTrader  decides WHETHER to take risk (direction / thesis / stop).
    Sizer        decides HOW MUCH risk is appropriate (deterministic).
    RiskEngine   decides whether that size is LEGALLY SAFE.
    Execution    decides how much the market can actually fill.

:class:`LiveEntrySizingService` is the ONLY final-quantity authority. The
LLM's ``position_size_request`` / ``requested_exposure`` are advisory only.
"""

from crypto_trader.sizing.audit import SizingAudit
from crypto_trader.sizing.conviction import (
    RiskFractionDecision,
    conviction_multiplier,
    risk_fraction_for_conviction,
)
from crypto_trader.sizing.policy import (
    HARD_MAX_LEVERAGE,
    HARD_MAX_NOTIONAL_MULTIPLE,
    HARD_MAX_RISK_PER_TRADE,
    PositionSizingPolicy,
)
from crypto_trader.sizing.risk_normalized import (
    RiskNormalizedSize,
    calculate_risk_normalized_size,
)
from crypto_trader.sizing.service import CanonicalSize, LiveEntrySizingService

__all__ = [
    "HARD_MAX_LEVERAGE",
    "HARD_MAX_NOTIONAL_MULTIPLE",
    "HARD_MAX_RISK_PER_TRADE",
    "CanonicalSize",
    "LiveEntrySizingService",
    "PositionSizingPolicy",
    "RiskFractionDecision",
    "RiskNormalizedSize",
    "SizingAudit",
    "calculate_risk_normalized_size",
    "conviction_multiplier",
    "risk_fraction_for_conviction",
]
