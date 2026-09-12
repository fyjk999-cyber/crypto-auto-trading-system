"""Compatibility wrapper. Canonical implementation lives in ai_brain."""

from __future__ import annotations

from crypto_trader.ai_brain.position_manager.manager import (
    PositionContext,
    PositionDecision,
    PositionManager,
)
from crypto_trader.ai_brain.position_manager.state import PositionLifecycle

PositionStateMachine = PositionLifecycle


class PositionIntelligence:
    """Thin wrapper around canonical PositionManager for legacy callers."""

    def __init__(self) -> None:
        self._manager = PositionManager()

    def decide(
        self,
        *,
        thesis_valid: bool,
        risk_increased: bool,
        opportunity_score: float,
        profit_factor: float = 0.0,
    ) -> str:
        thesis_status = "THESIS_INTACT" if thesis_valid else "THESIS_INVALIDATED"
        if risk_increased:
            thesis_status = "THESIS_WEAKENING"
        ctx = PositionContext(symbol="legacy", position_quantity=1.0, thesis_status=thesis_status)
        decision = self._manager.decide(ctx)
        return decision.action


__all__ = [
    "PositionContext",
    "PositionDecision",
    "PositionManager",
    "PositionLifecycle",
    "PositionStateMachine",
    "PositionIntelligence",
]
