"""Canonical position lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

VALID_TRANSITIONS = {
    "WATCHING": {"ENTERED"},
    "ENTERED": {"MONITORING"},
    "MONITORING": {"MONITORING", "ADJUSTING", "EXIT_PENDING"},
    "ADJUSTING": {"MONITORING", "EXIT_PENDING"},
    "EXIT_PENDING": {"EXIT_PENDING", "EXITED"},
    "EXITED": {"REVIEW"},
    "REVIEW": set(),
    "CANCELLED": {"WATCHING"},
}


@dataclass
class PositionLifecycle:
    state: str = "WATCHING"
    history: list[dict] = field(default_factory=list)

    def transition(self, new_state: str, reason: str = "") -> dict:
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(f"invalid transition {self.state} -> {new_state}")
        record = {
            "from": self.state,
            "to": new_state,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.state = new_state
        self.history.append(record)
        return record

    def can(self, new_state: str) -> bool:
        return new_state in VALID_TRANSITIONS.get(self.state, set())
