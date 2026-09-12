"""Daily AI market report generator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DailyAIReport:
    date: str
    regime: str
    risks: list[str]
    opportunities: list[str]
    coin_status: dict
    strategy_status: dict
    learning_updates: list[str]


class DailyAIReportGenerator:
    def generate(
        self,
        *,
        date: str,
        regime: str,
        risks: list[str],
        opportunities: list[str],
        coin_status: dict,
        strategy_status: dict,
        learning_updates: list[str],
    ) -> DailyAIReport:
        return DailyAIReport(
            date=date,
            regime=regime,
            risks=risks,
            opportunities=opportunities,
            coin_status=coin_status,
            strategy_status=strategy_status,
            learning_updates=learning_updates,
        )
