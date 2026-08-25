"""Idempotent job system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class JobResult:
    job_id: str
    status: str
    completed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class JobScheduler:
    def __init__(self) -> None:
        self.executed: set[str] = set()

    async def run_once(self, job_id: str, coro) -> JobResult:
        if job_id in self.executed:
            return JobResult(job_id=job_id, status="DUPLICATE_SKIPPED")
        self.executed.add(job_id)
        await coro()
        return JobResult(job_id=job_id, status="COMPLETED")
