"""Autonomous training scheduler."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScheduledTask:
    name: str
    interval: str  # DAILY | WEEKLY | MONTHLY


class TrainingScheduler:
    TASKS = [
        ScheduledTask("review_yesterday_trades", "DAILY"),
        ScheduledTask("update_memory", "DAILY"),
        ScheduledTask("generate_report", "DAILY"),
        ScheduledTask("strategy_evaluation", "WEEKLY"),
        ScheduledTask("coin_profile_update", "WEEKLY"),
        ScheduledTask("risk_review", "WEEKLY"),
        ScheduledTask("fund_performance_review", "MONTHLY"),
        ScheduledTask("strategy_retirement", "MONTHLY"),
        ScheduledTask("new_research", "MONTHLY"),
    ]

    def tasks_for(self, interval: str) -> list[str]:
        return [t.name for t in self.TASKS if t.interval == interval]
