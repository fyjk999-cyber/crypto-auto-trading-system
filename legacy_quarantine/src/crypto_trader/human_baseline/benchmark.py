"""Human trader baseline comparison."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ComparisonResult:
    decision_quality: float
    risk_adjusted_return: float
    consistency: float
    winner: str


class HumanBaselineBenchmark:
    def compare(
        self,
        *,
        ai_decision_quality: float,
        human_decision_quality: float,
        ai_risk_return: float,
        human_risk_return: float,
        ai_consistency: float,
        human_consistency: float,
    ) -> ComparisonResult:
        ai_score = ai_decision_quality + ai_risk_return + ai_consistency
        human_score = human_decision_quality + human_risk_return + human_consistency
        return ComparisonResult(
            decision_quality=ai_decision_quality - human_decision_quality,
            risk_adjusted_return=ai_risk_return - human_risk_return,
            consistency=ai_consistency - human_consistency,
            winner="AI" if ai_score >= human_score else "HUMAN",
        )
