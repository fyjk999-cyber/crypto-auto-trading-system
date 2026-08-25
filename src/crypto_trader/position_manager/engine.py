"""Position management: state machine + intelligence. No execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

VALID_STATES = (
    "WATCHING",
    "ENTERED",
    "MONITORING",
    "ADJUSTING",
    "EXIT_PENDING",
    "EXITED",
    "REVIEW",
)


@dataclass
class PositionStateMachine:
    state: str = "WATCHING"
    history: list[dict] = field(default_factory=list)

    def transition(self, new_state: str, reason: str = "") -> dict:
        if new_state not in VALID_STATES:
            raise ValueError(f"invalid state {new_state}")
        record = {
            "from": self.state,
            "to": new_state,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.state = new_state
        self.history.append(record)
        return record

    def allowed(self, new_state: str) -> bool:
        order = {s: i for i, s in enumerate(VALID_STATES)}
        return order.get(new_state, -1) >= order.get(self.state, -1)


@dataclass
class PositionIntelligence:
    def decide(
        self,
        *,
        thesis_valid: bool,
        risk_increased: bool,
        opportunity_score: float,
        profit_factor: float = 0.0,
    ) -> str:
        if not thesis_valid:
            return "EXIT"
        if risk_increased:
            return "REDUCE"
        if opportunity_score > 0.7 and profit_factor < 1.5:
            return "ADD"
        return "HOLD"
