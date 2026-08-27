"""Canonical UTC review runtime coordinator."""

from __future__ import annotations

from crypto_trader.evolution.time.review_period import period_for
from crypto_trader.evolution.time.review_schedule import ORDER, should_trigger


class RuntimeReviewCoordinator:
    def __init__(self, job_store=None) -> None:
        self.job_store = job_store

    async def run_due(self, now, callbacks: dict[str, callable]) -> list[dict]:
        results = []
        for period_type in ORDER:
            if not should_trigger(period_type, now):
                continue
            period = period_for(period_type, now)
            key = f"review:{period_type.lower()}:{period.period_id}"
            if self.job_store is not None:
                existing = await self.job_store.get(key)
                if existing and existing.get("status") == "DONE":
                    results.append({"period": period_type, "status": "SKIPPED_DONE"})
                    continue
            callback = callbacks.get(period_type)
            if callback is not None:
                import inspect

                result = callback(period)
                if inspect.isawaitable(result):
                    await result
            if self.job_store is not None:
                await self.job_store.put(
                    key,
                    f"review-{period_type.lower()}-{period.period_id}",
                    period_type,
                    period.period_id,
                    "DONE",
                )
            results.append({"period": period_type, "status": "COMPLETED"})
        return results
