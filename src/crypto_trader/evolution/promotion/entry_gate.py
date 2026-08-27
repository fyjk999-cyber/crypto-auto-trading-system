"""New entry gate: blocks only risk-increasing entries."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NewEntryGate:
    state: str = "OPEN"  # OPEN | BLOCKED_FOR_UPGRADE

    def block(self) -> None:
        self.state = "BLOCKED_FOR_UPGRADE"

    def open(self) -> None:
        self.state = "OPEN"

    def allows(self, *, reduce_only: bool, action: str) -> bool:
        if self.state == "OPEN":
            return True
        if reduce_only or action in ("REDUCE", "EXIT", "STOP_LOSS",
                                     "TAKE_PROFIT", "EMERGENCY_EXIT",
                                     "RISK_REDUCE"):
            return True
        return False
