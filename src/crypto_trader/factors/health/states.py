"""Explicit factor health states shared by capture, gateway and profiles.

These are per-calculation health states, distinct from the lifecycle health
in ``crypto_trader.factors.models.FactorHealth`` (EXPERIMENTAL/HEALTHY/...),
which tracks long-run factor usefulness rather than a single calculation.
"""


class FactorHealthState:
    OK = "OK"
    VALID_ZERO = "VALID_ZERO"
    MISSING_DATA = "MISSING_DATA"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE_INPUT = "STALE_INPUT"
    CALCULATION_FAILED = "CALCULATION_FAILED"
    DISABLED = "DISABLED"


ALL_STATES: tuple[str, ...] = (
    FactorHealthState.OK,
    FactorHealthState.VALID_ZERO,
    FactorHealthState.MISSING_DATA,
    FactorHealthState.INSUFFICIENT_HISTORY,
    FactorHealthState.STALE_INPUT,
    FactorHealthState.CALCULATION_FAILED,
    FactorHealthState.DISABLED,
)

# States whose numeric value may be trusted for decisions.
USABLE_STATES: tuple[str, ...] = (FactorHealthState.OK, FactorHealthState.VALID_ZERO)


def is_usable(state: str) -> bool:
    return state in USABLE_STATES
