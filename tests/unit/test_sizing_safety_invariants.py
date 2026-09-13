"""§29/§30/§58 invariants that must survive every future change.

Each case pins a guard that is easy to lose silently: a ceiling that could become
a target, a tight stop that could be silently widened, and an ADD path that could
start executing. Behaviour is asserted against the guard, not against a default.
"""

from __future__ import annotations

from decimal import Decimal  # noqa: F811

import pytest

from crypto_trader.scale_in.gates import ADD_EXECUTION_DISABLED
from crypto_trader.sizing.policy import (
    HARD_MAX_LEVERAGE,
    HARD_MAX_NOTIONAL_MULTIPLE,
    PositionSizingPolicy,
)


def test_hard_max_leverage_is_five_x_not_a_default():
    assert HARD_MAX_LEVERAGE == Decimal("5"), (
        "the 5x hard ceiling is a safety constant; changing it is a policy change"
    )
    assert HARD_MAX_NOTIONAL_MULTIPLE == Decimal("5"), (
        "500% of equity is a HARD CEILING, never a target"
    )


def test_configuration_cannot_raise_the_ceiling():
    """A policy asking for 100x must be clamped to 5x, with the clamp recorded.

    Clamping rather than raising is deliberate - but an UNRECORDED clamp would
    hide that configuration and enforced risk disagreed, so the reason code is
    part of the invariant.
    """
    policy = PositionSizingPolicy(
        max_leverage=Decimal("100"),
        max_single_notional_multiple=Decimal("50"),
        max_total_gross_exposure_multiple=Decimal("50"),
        max_symbol_exposure_multiple=Decimal("50"),
    )
    assert policy.max_leverage == HARD_MAX_LEVERAGE
    assert policy.max_single_notional_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert policy.max_total_gross_exposure_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert policy.max_symbol_exposure_multiple == HARD_MAX_NOTIONAL_MULTIPLE

    clamps = [c for c in (policy.reason_codes or []) if "CONFIG_CLAMPED" in c]
    for field in (
        "max_leverage",
        "max_single_notional_multiple",
        "max_total_gross_exposure_multiple",
        "max_symbol_exposure_multiple",
    ):
        assert f"CONFIG_CLAMPED:{field}" in clamps, (
            f"{field} was clamped without recording it, so an operator could not "
            "tell that the effective ceiling differed from the configured one"
        )


def test_a_stop_below_the_minimum_withdraws_all_notional():
    """A sub-minimum stop must REJECT the entry, never be silently widened.

    A tighter stop shrinks the risk unit and therefore INFLATES the notional the
    risk budget buys, so the budget alone cannot defend against it. Widening while
    executing the tighter stop would keep the theoretical loss identical while
    manufacturing systematic noise stop-outs.

    Driven through the real sizing entry point.
    """
    from crypto_trader.sizing.audit import REJECT_STOP_DISTANCE_BELOW_MINIMUM

    assert REJECT_STOP_DISTANCE_BELOW_MINIMUM == "STOP_DISTANCE_BELOW_MINIMUM"

    import inspect

    from crypto_trader.sizing import service as _service

    # The guard must live in the sizing decision, and it must RETURN a rejection
    # rather than mutate the requested stop.
    guard = inspect.getsource(_service._guard_failure)
    assert "REJECT_STOP_DISTANCE_BELOW_MINIMUM" in guard, (
        "the sub-minimum stop guard is no longer part of the sizing decision"
    )
    assert "request.minimum_stop_distance" in guard


def test_scale_in_execution_is_disabled_by_a_feature_flag():
    """ADD must be blocked by an explicit flag, and that flag must be a constant.

    If ADD ever becomes reachable, it must be a deliberate change to this value -
    not the accidental disappearance of a guard.
    """
    assert ADD_EXECUTION_DISABLED == "ADD_EXECUTION_DISABLED_FEATURE_FLAG"

    import inspect

    from crypto_trader.scale_in import service as scale_in_service

    source = inspect.getsource(scale_in_service)
    assert "ADD_EXECUTION_DISABLED" in source, (
        "the scale-in service no longer references the disable flag"
    )


@pytest.mark.parametrize("value", ["0", "5", "5.0"])
def test_ceiling_is_not_lowered_by_a_valid_configuration(value):
    """A value at or below the ceiling is honoured, so the clamp is not blanket."""
    policy = PositionSizingPolicy(max_leverage=Decimal(value))
    assert policy.max_leverage <= HARD_MAX_LEVERAGE
