"""Factor lifecycle manager."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.lifecycle.models import FactorLifecycleStatus
from crypto_trader.factors.lifecycle.rules import next_state


class FactorLifecycleManager:
    def __init__(self) -> None:
        self.states: dict[str, str] = {}

    def evaluate(
        self,
        *,
        factor: str,
        current_state: str,
        sample_size: int,
        win_rate: Decimal,
        sharpe: Decimal,
        decay_status: str,
    ) -> FactorLifecycleStatus:
        old = self.states.get(factor, current_state)
        state, reason = next_state(
            old,
            sample_size=sample_size,
            win_rate=win_rate,
            sharpe=sharpe,
            decay_status=decay_status,
        )
        self.states[factor] = state
        return FactorLifecycleStatus(factor=factor, state=state, old_state=old, reason=reason)

    def get(self, factor: str) -> str:
        return self.states.get(factor, "CANDIDATE")
