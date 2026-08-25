"""AI fund manager scorecard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FundScore:
    alpha: float
    risk: float
    decision_accuracy: float
    learning: float
    overall: float


class FundScorecard:
    def score(
        self, *, alpha: float, risk: float, decision_accuracy: float, learning: float
    ) -> FundScore:
        overall = 0.3 * alpha + 0.3 * risk + 0.25 * decision_accuracy + 0.15 * learning
        return FundScore(
            alpha=alpha,
            risk=risk,
            decision_accuracy=decision_accuracy,
            learning=learning,
            overall=round(overall, 3),
        )
