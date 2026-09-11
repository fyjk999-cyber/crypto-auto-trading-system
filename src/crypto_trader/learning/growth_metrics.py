"""G07: growth-learning observability metrics.

The metric set deliberately separates pipeline stages instead of reporting a
single vanity number:

* eligible / pending / reviewed / quarantined factual episodes;
* stats-complete, LLM-reviewed and knowledge-published job stages;
* retrieved and cited tool selections;
* schedule timing (last/next UTC review time, oldest backlog);
* claim state, stage failures, retries;
* provider usage where it is provable, with unknown-usage counted separately.

It never converts an unknown usage/cost into zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select

from crypto_trader.learning.growth_models import (
    GrowthCompressionORM,
    GrowthLearningJobORM,
    GrowthLessonORM,
    GrowthPatternORM,
    GrowthReviewAttemptORM,
    GrowthToolSelectionORM,
)
from crypto_trader.persistence.models import DailyReviewRunORM, TradeEpisodeORM


def next_utc_review_time(
    review_time_utc: str = "00:00", *, now: datetime | None = None
) -> datetime:
    now = now or datetime.now(UTC)
    hour, minute = (int(part) for part in review_time_utc.split(":"))
    candidate = datetime.combine(
        now.date(), time(hour=hour, minute=minute), tzinfo=UTC
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


@dataclass
class GrowthMetrics:
    generated_at: datetime
    factual_episodes: int = 0
    episodes_pending: int = 0
    episodes_reviewed: int = 0
    episodes_quarantined: int = 0
    stats_complete: int = 0
    llm_reviewed: int = 0
    knowledge_published: int = 0
    jobs_total: int = 0
    jobs_failed: int = 0
    jobs_retried: int = 0
    review_attempts_succeeded: int = 0
    review_attempts_failed: int = 0
    review_attempts_claim_lost: int = 0
    usage_known_tokens: int = 0
    usage_unknown_attempts: int = 0
    lessons_published: int = 0
    patterns_published: int = 0
    compressions_published: int = 0
    tool_selections: int = 0
    retrieved_refs: int = 0
    cited_refs: int = 0
    last_succeeded_review_date: str | None = None
    next_utc_review_at: datetime | None = None
    oldest_pending_closed_at: datetime | None = None
    oldest_backlog_days: float | None = None
    claim_active: int = 0
    claim_expired_running: int = 0
    schema_revision_note: str = "growth draft schema (not applied to production)"
    notes: list[str] = field(default_factory=list)


async def collect_growth_metrics(
    session_factory,
    *,
    now: datetime | None = None,
    review_time_utc: str = "00:00",
) -> GrowthMetrics:
    now = now or datetime.now(UTC)
    metrics = GrowthMetrics(generated_at=now)
    metrics.next_utc_review_at = next_utc_review_time(review_time_utc, now=now)
    async with session_factory() as session:
        metrics.factual_episodes = int(
            await session.scalar(
                select(func.count())
                .select_from(TradeEpisodeORM)
                .where(TradeEpisodeORM.factual.is_(True))
            )
            or 0
        )
        rows = (
            await session.execute(
                select(TradeEpisodeORM.review_status, func.count())
                .where(TradeEpisodeORM.factual.is_(True))
                .group_by(TradeEpisodeORM.review_status)
            )
        ).all()
        for status, count in rows:
            normalized = str(status or "UNKNOWN").upper()
            if normalized == "PENDING":
                metrics.episodes_pending += int(count)
            elif normalized == "REVIEWED":
                metrics.episodes_reviewed += int(count)
            elif normalized in {"QUARANTINED", "REVOKED", "FAILED"}:
                metrics.episodes_quarantined += int(count)

        metrics.oldest_pending_closed_at = await session.scalar(
            select(func.min(TradeEpisodeORM.closed_at)).where(
                TradeEpisodeORM.factual.is_(True),
                TradeEpisodeORM.review_status == "PENDING",
            )
        )
        if metrics.oldest_pending_closed_at is not None:
            oldest = metrics.oldest_pending_closed_at
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            metrics.oldest_backlog_days = max(
                0.0, (now - oldest).total_seconds() / 86400.0
            )

        metrics.last_succeeded_review_date = await session.scalar(
            select(func.max(DailyReviewRunORM.review_date)).where(
                DailyReviewRunORM.status == "SUCCEEDED"
            )
        )

        metrics.jobs_total = int(
            await session.scalar(select(func.count()).select_from(GrowthLearningJobORM))
            or 0
        )
        job_stages = (
            await session.execute(
                select(
                    GrowthLearningJobORM.stats_status,
                    GrowthLearningJobORM.review_status,
                    GrowthLearningJobORM.publish_status,
                    GrowthLearningJobORM.attempt_count,
                    GrowthLearningJobORM.claim_deadline_at,
                )
            )
        ).all()
        for stats_status, review_status, publish_status, attempts, deadline in job_stages:
            if stats_status == "SUCCEEDED":
                metrics.stats_complete += 1
            if review_status == "SUCCEEDED":
                metrics.llm_reviewed += 1
            if publish_status == "SUCCEEDED":
                metrics.knowledge_published += 1
            if "FAILED" in {str(stats_status), str(review_status), str(publish_status)}:
                metrics.jobs_failed += 1
            if (attempts or 0) > 1:
                metrics.jobs_retried += 1
            if deadline is not None:
                aware = deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
                if aware >= now:
                    metrics.claim_active += 1
                elif str(stats_status) == "RUNNING" or str(review_status) == "RUNNING":
                    metrics.claim_expired_running += 1

        attempts = (
            await session.execute(
                select(
                    GrowthReviewAttemptORM.status,
                    GrowthReviewAttemptORM.usage_status,
                    GrowthReviewAttemptORM.usage_json,
                )
            )
        ).all()
        for status, usage_status, usage in attempts:
            normalized = str(status or "").upper()
            if normalized == "SUCCEEDED":
                metrics.review_attempts_succeeded += 1
            elif normalized == "FAILED":
                metrics.review_attempts_failed += 1
            elif normalized == "CLAIM_LOST":
                metrics.review_attempts_claim_lost += 1
            if str(usage_status or "UNKNOWN").upper() == "KNOWN" and isinstance(usage, dict):
                metrics.usage_known_tokens += int(
                    usage.get("total_tokens")
                    or (usage.get("prompt_tokens", 0) or 0)
                    + (usage.get("completion_tokens", 0) or 0)
                )
            else:
                metrics.usage_unknown_attempts += 1

        metrics.lessons_published = int(
            await session.scalar(
                select(func.count())
                .select_from(GrowthLessonORM)
                .where(GrowthLessonORM.status.in_(("VALIDATED", "CONTESTED")))
            )
            or 0
        )
        metrics.patterns_published = int(
            await session.scalar(
                select(func.count())
                .select_from(GrowthPatternORM)
                .where(GrowthPatternORM.status.in_(("VALIDATED", "CONTESTED")))
            )
            or 0
        )
        metrics.compressions_published = int(
            await session.scalar(
                select(func.count())
                .select_from(GrowthCompressionORM)
                .where(GrowthCompressionORM.status == "PUBLISHED")
            )
            or 0
        )
        selections = (
            await session.execute(
                select(
                    GrowthToolSelectionORM.returned_refs_json,
                    GrowthToolSelectionORM.evidence_package_json,
                )
            )
        ).all()
        metrics.tool_selections = len(selections)
        for refs, package in selections:
            metrics.retrieved_refs += len(list(refs or []))
            if isinstance(package, dict):
                metrics.cited_refs += len(list(package.get("source_refs") or []))
        if metrics.tool_selections == 0:
            metrics.notes.append("no ChiefTrader tool selection recorded yet")
        if metrics.usage_unknown_attempts:
            metrics.notes.append(
                f"{metrics.usage_unknown_attempts} provider attempt(s) have UNKNOWN usage"
            )
        if metrics.oldest_backlog_days and metrics.oldest_backlog_days > 1:
            metrics.notes.append(
                f"oldest pending episode is {metrics.oldest_backlog_days:.1f} days old"
            )
    return metrics
