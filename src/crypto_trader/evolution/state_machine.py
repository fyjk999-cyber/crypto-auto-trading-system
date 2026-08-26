"""Persistent Evolution state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

VALID_STATES = (
    "IDLE",
    "REVIEW_READY",
    "OBSERVE",
    "DIAGNOSE",
    "LESSON",
    "HYPOTHESIZE",
    "PROPOSE",
    "MATERIALIZE",
    "STATIC_VALIDATE",
    "BACKTEST",
    "OOS",
    "WALK_FORWARD",
    "STRESS",
    "SHADOW",
    "CERTIFY",
    "READY_FOR_UPGRADE",
    "WAIT_SAFE_WINDOW",
    "ACTIVATE",
    "VERIFY",
    "ACTIVE",
    "REJECTED",
    "QUARANTINED",
    "ROLLBACK",
)

TERMINAL_STATES = ("ACTIVE", "REJECTED", "QUARANTINED", "ROLLBACK")


@dataclass
class EvolutionStateMachine:
    state: str = "IDLE"
    history: list[dict] = field(default_factory=list)

    def transition(self, new_state: str, reason: str = "") -> dict:
        if new_state not in VALID_STATES:
            raise ValueError(f"invalid evolution state {new_state}")
        if self.state in TERMINAL_STATES and new_state != "IDLE":
            raise ValueError(f"terminal state {self.state} cannot transition")
        record = {
            "from": self.state,
            "to": new_state,
            "reason": reason,
            "at": datetime.now(UTC).isoformat(),
        }
        self.state = new_state
        self.history.append(record)
        return record

    def reset(self) -> None:
        self.state = "IDLE"
        self.history = []
