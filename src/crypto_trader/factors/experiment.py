"""Factor experiment framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorExperiment:
    experiment_id: str
    hypothesis: str
    factor: str
    dataset: str
    timeframe: str
    method: str
    result: str = "PENDING"
    confidence: float = 0.0
    conclusion: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ExperimentRunner:
    def run(
        self,
        experiment_id: str,
        hypothesis: str,
        factor: str,
        dataset: str,
        timeframe: str,
        observations: list[dict],
    ) -> FactorExperiment:
        total = len(observations)
        wins = sum(1 for o in observations if o.get("result") == "WIN")
        win_rate = wins / total if total else 0.0
        if total < 30:
            result, confidence, conclusion = "INSUFFICIENT", 0.3, "need more data"
        elif win_rate > 0.55:
            result, confidence, conclusion = "VALIDATED", min(0.9, 0.4 + total / 200), "predictive"
        else:
            result, confidence, conclusion = "REJECTED", 0.5, "no edge"
        return FactorExperiment(
            experiment_id,
            hypothesis,
            factor,
            dataset,
            timeframe,
            "walk_forward",
            result,
            confidence,
            conclusion,
        )
