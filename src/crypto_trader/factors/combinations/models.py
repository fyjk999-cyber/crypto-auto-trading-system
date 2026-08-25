"""Factor combination models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorCombination:
    name: str
    factors: list[str]
    performance: dict = field(default_factory=dict)
    status: str = "TESTING"  # CANDIDATE|TESTING|VALIDATED|REJECTED
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "factors": self.factors,
            "performance": self.performance,
            "status": self.status,
            "created_at": self.created_at,
        }
