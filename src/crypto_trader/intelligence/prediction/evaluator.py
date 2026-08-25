"""Prediction evaluator: tracks accuracy, not profit."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PredictionEvaluator:
    records: list[dict] = field(default_factory=list)

    def record(self, prediction: dict, actual: str) -> None:
        self.records.append({"prediction": prediction, "actual": actual})

    def accuracy(self) -> float:
        if not self.records:
            return 0.0
        correct = 0
        for r in self.records:
            prediction = r["prediction"]
            actual = r["actual"]
            if isinstance(prediction, dict):
                if actual in prediction or actual in prediction.values():
                    correct += 1
            elif actual == str(prediction):
                correct += 1
        return correct / len(self.records)
