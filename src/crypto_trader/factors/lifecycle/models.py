"""Factor lifecycle models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorLifecycleStatus:
    factor: str
    state: str
    old_state: str = ""
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "state": self.state,
            "old_state": self.old_state,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
