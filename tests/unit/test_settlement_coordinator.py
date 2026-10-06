"""Coordinator invariants; not production or trading-acceptance evidence."""

import pytest

from crypto_trader.execution.settlement import SettlementCoordinator


def test_overlapping_tokens_never_make_account_coherent_early():
    coordinator = SettlementCoordinator()
    coordinator.begin("first")
    coordinator.begin("second")
    coordinator.complete("first")
    assert coordinator.snapshot()["state"] == "PENDING_SETTLEMENT"
    assert coordinator.snapshot()["active_count"] == 1
    coordinator.complete("second")
    assert coordinator.snapshot()["state"] == "COHERENT"


def test_stuck_token_and_fault_are_fail_closed():
    current = [0.0]
    coordinator = SettlementCoordinator(stale_seconds=120, clock=lambda: current[0])
    coordinator.begin("fill")
    current[0] = 121.0
    assert coordinator.snapshot()["state"] == "SETTLEMENT_STALE"
    coordinator.fault("fill", "fixture durable write failure")
    coordinator.complete("fill")
    assert coordinator.snapshot()["state"] == "SETTLEMENT_FAULT"
    assert coordinator.snapshot()["active_count"] == 1


@pytest.mark.parametrize("threshold", [0, -1, float("nan"), float("inf"), True])
def test_invalid_stale_deadline_is_rejected(threshold):
    with pytest.raises(ValueError):
        SettlementCoordinator(stale_seconds=threshold)
