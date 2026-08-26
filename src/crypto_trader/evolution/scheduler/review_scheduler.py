"""Evolution Review Scheduler: idempotent UTC review runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from crypto_trader.evolution.time.review_period import period_for
from crypto_trader.evolution.time.review_schedule import ORDER, should_trigger


@dataclass
class ReviewRunRecord:
    period_type: str
    period_id: str
    scheduled_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str = "PENDING"
    attempt: int = 0
    error: str = ""
    report_id: str = ""


class EvolutionReviewScheduler:
    def __init__(self, clock=None) -> None:
        self.clock = clock
        self.runs: dict[str, ReviewRunRecord] = {}

    def _idempotency_key(self, period_type: str, period_id: str) -> str:
        return f"review:{period_type.lower()}:{period_id}"

    def due(self, now: datetime) -> list[str]:
        return [ptype for ptype in ORDER if self._should_run(ptype, now)]

    def _should_run(self, period_type: str, now: datetime) -> bool:
        if not should_trigger(period_type, now):
            return False
        period = period_for(period_type, now)
        key = self._idempotency_key(period_type, period.period_id)
        return key not in self.runs or self.runs[key].status in ("FAILED", "PENDING")

    def schedule(self, period_type: str, now: datetime) -> str:
        period = period_for(period_type, now)
        key = self._idempotency_key(period_type, period.period_id)
        if key not in self.runs:
            self.runs[key] = ReviewRunRecord(period_type, period.period_id, now)
        else:
            self.runs[key].attempt += 1
            self.runs[key].status = "PENDING"
        return key

    def mark_started(self, key: str, now: datetime) -> None:
        run = self.runs[key]
        run.started_at = now
        run.status = "RUNNING"

    def mark_completed(self, key: str, now: datetime, report_id: str = "") -> None:
        run = self.runs[key]
        run.completed_at = now
        run.status = "COMPLETED"
        run.report_id = report_id

    def mark_failed(self, key: str, error: str) -> None:
        run = self.runs[key]
        run.status = "FAILED"
        run.error = error

    def run_serially(self, now: datetime, review_callbacks: dict[str, callable] | None = None):
        review_callbacks = review_callbacks or {}
        results = []
        for period_type in ORDER:
            if self._should_run(period_type, now):
                period = period_for(period_type, now)
                key = self.schedule(period_type, now)
                self.mark_started(key, now)
                callback = review_callbacks.get(period_type)
                if callback:
                    callback(period)
                self.mark_completed(key, now, report_id=f"{key}:report")
                results.append((period_type, period.period_id, "COMPLETED"))
        return results
