"""Strategy lifecycle management."""

from __future__ import annotations


class StrategyLifecycle:
    STATES = [
        "DISCOVERY",
        "EXPERIMENTAL",
        "VALIDATING",
        "PAPER",
        "SHADOW",
        "ACTIVE",
        "DEGRADING",
        "RETIRED",
    ]

    def __init__(self) -> None:
        self.states: dict[str, str] = {}

    def set_state(self, strategy: str, state: str) -> None:
        if state not in self.STATES:
            raise ValueError(f"invalid state {state}")
        self.states[strategy] = state

    def get_state(self, strategy: str) -> str:
        return self.states.get(strategy, "DISCOVERY")
