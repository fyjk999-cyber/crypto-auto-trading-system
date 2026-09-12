"""Large-scale paper training evaluator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrainingEvalResult:
    episode_count: int
    coverage_symbols: list[str]
    decision_accuracy: float
    calibration_error: float
    failure_reasons: dict
    learning_improvement: float


class AITrainingEvaluator:
    def evaluate(self, *, episodes: list[dict]) -> TrainingEvalResult:
        symbols = list(dict.fromkeys(e["symbol"] for e in episodes))
        correct = sum(1 for e in episodes if e.get("result") == "CORRECT")
        accuracy = correct / len(episodes) if episodes else 0.0
        calibration = (
            sum(abs(e.get("confidence", 0) - e.get("actual", 0)) for e in episodes) / len(episodes)
            if episodes
            else 0.0
        )
        failures: dict[str, int] = {}
        for e in episodes:
            if e.get("result") != "CORRECT":
                reason = e.get("failure_reason", "UNKNOWN")
                failures[reason] = failures.get(reason, 0) + 1
        return TrainingEvalResult(
            episode_count=len(episodes),
            coverage_symbols=symbols,
            decision_accuracy=accuracy,
            calibration_error=calibration,
            failure_reasons=failures,
            learning_improvement=max(0.0, accuracy - 0.5),
        )
