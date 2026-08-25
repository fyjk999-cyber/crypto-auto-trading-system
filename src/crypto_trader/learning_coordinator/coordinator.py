"""Daily learning cycle coordinator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LearningReport:
    trades_analyzed: int
    new_patterns: list[str]
    failed_decisions: list[str]
    updated_profiles: list[str]
    compressed_lessons: list[str]
    improvement_suggestions: list[str]


class LearningCoordinator:
    def run_daily(
        self,
        *,
        yesterday_trades: list[dict],
        market_changes: list[str],
        new_patterns: list[str],
        failed_decisions: list[str],
    ) -> LearningReport:
        lessons = [t.get("lesson", "review trade") for t in yesterday_trades if t.get("lesson")]
        return LearningReport(
            trades_analyzed=len(yesterday_trades),
            new_patterns=new_patterns,
            failed_decisions=failed_decisions,
            updated_profiles=[t["symbol"] for t in yesterday_trades],
            compressed_lessons=lessons[:3],
            improvement_suggestions=market_changes + new_patterns,
        )
