"""Lifecycle transition rules."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D

VALID_STATES = (
    "CANDIDATE",
    "TESTING",
    "VALIDATED",
    "ACTIVE",
    "WARNING",
    "DEGRADING",
    "REVIEW",
    "RETIRED",
)


def next_state(
    current: str, *, sample_size: int, win_rate: Decimal, sharpe: Decimal, decay_status: str
) -> tuple[str, str]:
    win = D(win_rate)
    sharpe = D(sharpe)
    if current == "CANDIDATE":
        if sample_size >= 10:
            return "TESTING", "sample threshold reached"
        return current, "insufficient sample"
    if current == "TESTING":
        if sample_size >= 30 and win >= Decimal("0.55") and sharpe >= Decimal("0.5"):
            return "VALIDATED", "performance threshold reached"
        if sample_size >= 100 and (win < Decimal("0.45") or sharpe < Decimal("0")):
            return "RETIRED", "poor performance"
        return current, "collecting evidence"
    if current in ("VALIDATED", "ACTIVE"):
        if decay_status == "DEGRADING":
            return "WARNING", "decay detected"
        if sample_size >= 30:
            return "ACTIVE", "active"
        return current, "ok"
    if current == "WARNING":
        if decay_status == "DEGRADING":
            return "DEGRADING", "continued decay"
        return "ACTIVE", "performance recovered"
    if current == "DEGRADING":
        if decay_status == "DEGRADING":
            return "REVIEW", "review required"
        return "ACTIVE", "recovered"
    if current == "REVIEW":
        if decay_status == "DEGRADING":
            return "RETIRED", "retired after review"
        return "ACTIVE", "restored after review"
    return current, "terminal state"
