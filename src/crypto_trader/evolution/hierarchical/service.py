"""Wiring between review periods, aggregation engine, and durable stores.

This module composes existing canonical components only:

- ``crypto_trader.evolution.time.review_period`` for UTC period selection,
- ``HierarchicalLearningEngine`` for deterministic aggregation,
- ``HierarchicalReviewStore`` / ``HierarchicalReviewJobStore`` for persistence,
- ``SqlEvidenceBackend`` for fetching completed Daily reports.

It introduces no scheduler loop, no new tables, and never mutates production
factor weights, strategy state, or live configuration: every output is a
canonical report whose recommendations are proposal-only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.evolution.hierarchical.engine import (
    HierarchicalLearningEngine,
    _expected_period_ids,
)
from crypto_trader.evolution.persistence_backends import (
    HierarchicalReviewJobStore,
    HierarchicalReviewStore,
    SqlEvidenceBackend,
)
from crypto_trader.evolution.time.review_period import period_for

PERIOD_TYPES = ("WEEKLY", "MONTHLY", "YEARLY")

# Which child granularity feeds each level, and which engine kwarg receives it.
_CHILD_CONFIG = {
    "WEEKLY": ("day", "daily_reviews"),
    "MONTHLY": ("week", "weekly_reviews"),
    "YEARLY": ("month", "monthly_reviews"),
}


def idempotency_key(period_type: str, period_id: str) -> str:
    """Canonical review key shared with EvolutionReviewScheduler convention."""
    return f"review:{period_type.lower()}:{period_id}"


class HierarchicalReviewService:
    """Idempotent runner for Weekly/Monthly/Yearly aggregations."""

    def __init__(
        self,
        *,
        evidence_backend: SqlEvidenceBackend,
        review_store: HierarchicalReviewStore,
        job_store: HierarchicalReviewJobStore,
        engine: HierarchicalLearningEngine | None = None,
    ) -> None:
        self.evidence_backend = evidence_backend
        self.review_store = review_store
        self.job_store = job_store
        self.engine = engine or HierarchicalLearningEngine()

    # ------------------------------------------------------------------ public

    async def run(self, period_type: str, now: datetime) -> dict:
        """Run one canonical review for the completed period before ``now``."""
        ptype = str(period_type).upper()
        if ptype not in PERIOD_TYPES:
            raise ValueError(f"unsupported review period_type: {period_type!r}")

        period = period_for(ptype, now)
        key = idempotency_key(ptype, period.period_id)

        # Idempotency gate 1: a completed job with a stored report short-circuits.
        job = await self.job_store.get(key)
        if job is not None and job.get("status") == "COMPLETED":
            existing = await self.review_store.get_review(ptype, str(job.get("review_id", "")))
            if existing is not None:
                return existing

        review_id = f"review-{ptype.lower()}-{period.period_id}"
        starts_at = period.starts_at.astimezone(UTC).isoformat()
        ends_at = period.ends_at.astimezone(UTC).isoformat()
        try:
            children = await self._collect_children(ptype, period.starts_at, period.ends_at)
            result = self._aggregate(
                ptype,
                review_id=review_id,
                period_id=period.period_id,
                starts_at=starts_at,
                ends_at=ends_at,
                children=children,
            )
            payload = result.to_dict()
            # Idempotency gate 2: store_review upserts once per deterministic id.
            await self.review_store.store_review(ptype, payload)
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim on the job row
            await self.job_store.put(key, review_id, ptype, period.period_id, "FAILED", str(exc))
            raise
        await self.job_store.put(key, review_id, ptype, period.period_id, "COMPLETED")
        return payload

    async def run_weekly(self, now: datetime) -> dict:
        return await self.run("WEEKLY", now)

    async def run_monthly(self, now: datetime) -> dict:
        return await self.run("MONTHLY", now)

    async def run_yearly(self, now: datetime) -> dict:
        return await self.run("YEARLY", now)

    # ----------------------------------------------------------------- private

    async def _collect_children(
        self, ptype: str, starts_at: datetime, ends_at: datetime
    ) -> list[dict]:
        """Fetch completed child reports for every expected sub-period."""
        granularity, _kwarg = _CHILD_CONFIG[ptype]
        children: list[dict] = []
        for child_id in _expected_period_ids(
            starts_at.isoformat(), ends_at.isoformat(), granularity
        ):
            if ptype == "WEEKLY":
                children.extend(await self.evidence_backend.list_reviews_by_period(child_id))
            elif ptype == "MONTHLY":
                children.extend(await self.review_store.list_period("WEEKLY", child_id))
            else:
                children.extend(await self.review_store.list_period("MONTHLY", child_id))
        return self._collapse_per_period(children)

    @staticmethod
    def _collapse_per_period(children: list[dict]) -> list[dict]:
        """One canonical report per child period: first occurrence by
        (period_id, review_id) wins, later siblings for the same sub-period
        are ignored instead of being double-counted."""
        seen_periods: set[str] = set()
        unique: list[dict] = []
        for review in sorted(
            children,
            key=lambda r: (str(r.get("period_id", "")), str(r.get("review_id", ""))),
        ):
            period = str(review.get("period_id", ""))
            if period in seen_periods:
                continue
            seen_periods.add(period)
            unique.append(review)
        return unique

    def _aggregate(
        self,
        ptype: str,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        children: list[dict],
    ):
        _granularity, kwarg = _CHILD_CONFIG[ptype]
        method = getattr(self.engine, f"{ptype.lower()}_review")
        return method(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            **{kwarg: children},
        )
