from __future__ import annotations

from crypto_trader.domain.enums import RuntimeState
from crypto_trader.domain.errors import InvalidStateTransition


class RuntimeStateMachine:
    TRANSITIONS = {
        RuntimeState.STOPPED: {RuntimeState.STARTING, RuntimeState.RECOVERING},
        RuntimeState.STARTING: {RuntimeState.RUNNING, RuntimeState.RECOVERING, RuntimeState.STOPPED},
        RuntimeState.RECOVERING: {RuntimeState.RUNNING, RuntimeState.STOPPED},
        RuntimeState.RUNNING: {RuntimeState.HALTED, RuntimeState.STOPPING},
        RuntimeState.HALTED: {RuntimeState.RUNNING, RuntimeState.STOPPING},
        RuntimeState.STOPPING: {RuntimeState.STOPPED},
    }

    def __init__(self) -> None:
        self.state = RuntimeState.STOPPED

    def transition(self, new_state: RuntimeState) -> None:
        if new_state not in self.TRANSITIONS.get(self.state, set()):
            raise InvalidStateTransition(f"{self.state.value} -> {new_state.value} invalid")
        self.state = new_state
