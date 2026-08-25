"""Factor evolution engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorEvolutionStatus:
    factor: str
    stage: str
    sample_size: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "stage": self.stage,
            "sample_size": self.sample_size,
            "timestamp": self.timestamp,
        }


class FactorEvolutionEngine:
    def evaluate(
        self, *, factor: str, sample_size: int, win_rate: float, sharpe: float
    ) -> FactorEvolutionStatus:
        if sample_size < 30:
            stage = "BIRTH"
        elif win_rate >= 0.55 and sharpe >= 0.5:
            stage = "MATURITY"
        elif win_rate < 0.45 or sharpe < 0.2:
            stage = "DECLINE"
        else:
            stage = "TESTING"
        return FactorEvolutionStatus(factor=factor, stage=stage, sample_size=sample_size)
