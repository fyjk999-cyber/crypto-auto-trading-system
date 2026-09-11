"""G03: staged, fenced, idempotent growth-learning pipeline.

Separation of durable state
---------------------------
``growth_learning_jobs`` tracks three independent stages:

* ``stats_status``   — deterministic factual statistics (never calls an LLM);
* ``review_status``  — structured provider attempts (G02);
* ``publish_status`` — knowledge promotion (G04).

A single ``SUCCEEDED`` can therefore never hide a failed review or publish.

Claim/fence reuse
-----------------
The day-level claim and fence are the **existing** ``MemoryPersistence``
claim on ``daily_review_runs`` (claim token + owner + deadline + attempt
count), the same primitive used by ``DailyReviewScheduler``.  Every stage
commit and every publish re-checks the live token first; a stale token can
never publish a visible result.  The growth job row mirrors the token/owner
for audit and revision lineage.

External calls
--------------
Structured provider calls happen through ``review_runner`` outside any DB
transaction (G02).  This module never wraps a provider call in a transaction
and never promises exactly-once external billing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import select, update

from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.learning.growth_models import (
    GrowthLearningJobORM,
    GrowthReviewAttemptORM,
    utcnow,
)
from crypto_trader.learning.growth_review import ReviewAttemptStore

STAGE_PENDING = "PENDING"
STAGE_RUNNING = "RUNNING"
STAGE_SUCCEEDED = "SUCCEEDED"
STAGE_FAILED = "FAILED"
STAGE_PARTIAL = "PARTIAL"
STAGE_SKIPPED_INCOMPLETE = "SKIPPED_INCOMPLETE"
STAGE_CLAIM_LOST = "CLAIM_LOST"

_GATE_STAGES = ("stats", "review", "publish")


def identity_key(
    *,
    account_id: str,
    mode: str,
    review_date: str,
    source_revision: str,
    profile_version: str,
) -> str:
    raw = "|".join((account_id, mode, review_date, source_revision, profile_version))
    return f"job_{sha256(raw.encode('utf-8')).hexdigest()[:48]}"


@dataclass
class StageOutcome:
    status: str
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    review_date: str
    job_key: str
    revision: int
    idempotent: bool
    stats_status: str
    review_status: str
    publish_status: str
    net_status: str = "UNKNOWN"
    reviewed_count: int = 0
    review_failed_count: int = 0
    published_count: int = 0
    error_type: str | None = None
    error_detail: str | None = None
    claim_owner: str | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.stats_status == STAGE_SUCCEEDED
            and self.review_status in {STAGE_SUCCEEDED, STAGE_SKIPPED_INCOMPLETE}
            and self.publish_status in {STAGE_SUCCEEDED, STAGE_SKIPPED_INCOMPLETE}
        )


def _job_complete(row: GrowthLearningJobORM) -> bool:
    return (
        row.stats_status == STAGE_SUCCEEDED
        and row.review_status in {STAGE_SUCCEEDED, STAGE_SKIPPED_INCOMPLETE}
        and row.publish_status in {STAGE_SUCCEEDED, STAGE_SKIPPED_INCOMPLETE}
    )


class GrowthJobStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def latest(self, job_key: str) -> GrowthLearningJobORM | None:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(GrowthLearningJobORM)
                    .where(GrowthLearningJobORM.job_key == job_key)
                    .order_by(GrowthLearningJobORM.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def successful_attempt_count(self, review_date: str) -> int:
        from sqlalchemy import func

        async with self.session_factory() as session:
            value = (
                await session.execute(
                    select(func.count())
                    .select_from(GrowthReviewAttemptORM)
                    .where(
                        GrowthReviewAttemptORM.review_date == review_date,
                        GrowthReviewAttemptORM.status == STAGE_SUCCEEDED,
                    )
                )
            ).scalar_one()
            return int(value or 0)

    async def all_for_key(self, job_key: str) -> list[GrowthLearningJobORM]:
        async with self.session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(GrowthLearningJobORM)
                        .where(GrowthLearningJobORM.job_key == job_key)
                        .order_by(GrowthLearningJobORM.revision.asc())
                    )
                )
                .scalars()
                .all()
            )

    async def claim(
        self,
        *,
        job_key: str,
        account_id: str,
        mode: str,
        review_date: str,
        source_revision: str,
        profile_version: str,
        input_hash: str,
        claim_token: str,
        owner: str,
        lease_seconds: int,
    ) -> tuple[GrowthLearningJobORM, bool]:
        """Return ``(job_row, idempotent)``.

        A complete job with the same input hash is idempotent.  A complete job
        with a different input hash (late episode / funding revision) opens the
        next revision and records ``superseded_by_revision`` on the old row.
        """
        now = utcnow()
        deadline = now + timedelta(seconds=max(60, lease_seconds))
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthLearningJobORM)
                    .where(GrowthLearningJobORM.job_key == job_key)
                    .order_by(GrowthLearningJobORM.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if row is not None and row.input_hash == input_hash and _job_complete(row):
                return row, True

            if row is not None and row.input_hash != input_hash and _job_complete(row):
                next_revision = row.revision + 1
                row.superseded_by_revision = next_revision
                new_row = GrowthLearningJobORM(
                    job_key=job_key,
                    account_id=account_id,
                    mode=mode,
                    review_date=review_date,
                    source_revision=source_revision,
                    profile_version=profile_version,
                    revision=next_revision,
                    input_hash=input_hash,
                    stats_status=STAGE_PENDING,
                    review_status=STAGE_PENDING,
                    publish_status=STAGE_PENDING,
                    claim_token=claim_token,
                    claim_owner=owner,
                    claim_fence=1,
                    claim_deadline_at=deadline,
                    attempt_count=1,
                    started_at=now,
                    heartbeat_at=now,
                )
                session.add(new_row)
                await session.commit()
                return new_row, False

            if row is None:
                row = GrowthLearningJobORM(
                    job_key=job_key,
                    account_id=account_id,
                    mode=mode,
                    review_date=review_date,
                    source_revision=source_revision,
                    profile_version=profile_version,
                    revision=1,
                    input_hash=input_hash,
                    stats_status=STAGE_PENDING,
                    review_status=STAGE_PENDING,
                    publish_status=STAGE_PENDING,
                    claim_token=claim_token,
                    claim_owner=owner,
                    claim_fence=1,
                    claim_deadline_at=deadline,
                    attempt_count=1,
                    started_at=now,
                    heartbeat_at=now,
                )
                session.add(row)
                await session.commit()
                return row, False

            # Resume/retry of an incomplete revision.  SUCCEEDED stages stay
            # SUCCEEDED; FAILED/PENDING stages become PENDING again.
            row.input_hash = input_hash
            row.claim_token = claim_token
            row.claim_owner = owner
            row.claim_fence = (row.claim_fence or 0) + 1
            row.claim_deadline_at = deadline
            row.attempt_count = (row.attempt_count or 0) + 1
            row.started_at = row.started_at or now
            row.heartbeat_at = now
            row.last_error_type = None
            row.last_error_detail_sanitized = None
            for stage in _GATE_STAGES:
                current = getattr(row, f"{stage}_status")
                if current not in {STAGE_SUCCEEDED, STAGE_SKIPPED_INCOMPLETE}:
                    setattr(row, f"{stage}_status", STAGE_PENDING)
            await session.commit()
            return row, False

    async def update_stage(
        self,
        *,
        job_id: int,
        stage: str,
        status: str,
        claim_token: str,
        claim_owner: str,
        claim_fence: int,
        lease_seconds: int,
        detail: str | None = None,
    ) -> bool:
        """Fenced CAS update.  False means the claim is stale/not the owner."""
        now = utcnow()
        deadline = now + timedelta(seconds=max(60, lease_seconds))
        values: dict[str, Any] = {
            f"{stage}_status": status,
            "heartbeat_at": now,
            "claim_deadline_at": deadline,
            "updated_at": now,
        }
        if status == STAGE_SUCCEEDED:
            values[f"{stage}_completed_at"] = now
        if detail is not None:
            values["last_error_type"] = stage.upper()
            values["last_error_detail_sanitized"] = detail[:255]
        async with self.session_factory() as session:
            result = await session.execute(
                update(GrowthLearningJobORM)
                .where(
                    GrowthLearningJobORM.id == job_id,
                    GrowthLearningJobORM.claim_token == claim_token,
                    GrowthLearningJobORM.claim_owner == claim_owner,
                    GrowthLearningJobORM.claim_fence == claim_fence,
                    GrowthLearningJobORM.claim_deadline_at.is_not(None),
                    GrowthLearningJobORM.claim_deadline_at >= now,
                )
                .values(**values)
            )
            await session.commit()
            return result.rowcount == 1

    async def record_claim_lost(self, *, job_id: int, claim_token: str, owner: str) -> bool:
        """Mark the attempt abandoned only if it is still the recorded claimant."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(GrowthLearningJobORM)
                .where(
                    GrowthLearningJobORM.id == job_id,
                    GrowthLearningJobORM.claim_token == claim_token,
                    GrowthLearningJobORM.claim_owner == owner,
                )
                .values(
                    last_error_type="CLAIM_LOST",
                    last_error_detail_sanitized="claim token is no longer live",
                    updated_at=utcnow(),
                )
            )
            await session.commit()
            return result.rowcount == 1


AsyncRunner = Callable[[], Awaitable[StageOutcome]]
ReviewLoader = Callable[[], Awaitable[list[Any]]]
ReviewRunner = Callable[[Any], Awaitable[Any]]
Publisher = Callable[..., Awaitable[StageOutcome]]


async def _call_publisher(publisher, stats, publish_inputs, *, fence, claim_guard=None):
    """Call a publisher, passing the claim guard only when it accepts one."""
    import inspect

    try:
        parameters = inspect.signature(publisher).parameters
    except (TypeError, ValueError):  # builtins / partials
        parameters = {}
    if "claim_guard" in parameters:
        return await publisher(
            stats, publish_inputs, fence=fence, claim_guard=claim_guard
        )
    return await publisher(stats, publish_inputs, fence=fence)


class GrowthLearningPipeline:
    def __init__(
        self,
        session_factory,
        *,
        owner: str = "growth-pipeline",
        lease_seconds: int = 1800,
    ) -> None:
        self.session_factory = session_factory
        self.owner = owner
        self.lease_seconds = max(60, lease_seconds)
        self.persistence = MemoryPersistence(session_factory)
        self.jobs = GrowthJobStore(session_factory)
        self.review_store = ReviewAttemptStore(session_factory)

    async def run_day(
        self,
        *,
        review_date: str,
        account_id: str,
        mode: str,
        source_revision: str,
        profile_version: str,
        input_hash: str,
        stats_runner: AsyncRunner,
        review_inputs_loader: ReviewLoader,
        review_runner: ReviewRunner,
        publisher: Publisher,
        allow_revision: bool | None = None,
    ) -> PipelineResult:
        job_key = identity_key(
            account_id=account_id,
            mode=mode,
            review_date=review_date,
            source_revision=source_revision,
            profile_version=profile_version,
        )
        latest = await self.jobs.latest(job_key)
        if latest is not None and latest.input_hash == input_hash and _job_complete(latest):
            return _result_from_row(latest, idempotent=True)

        # ``begin_daily_review`` with allow_revision=True is only needed when a
        # previously complete job must be superseded by changed inputs.
        if allow_revision is None:
            day_row = await self.persistence.get_daily_review(review_date)
            day_is_published = bool(day_row and day_row.get("status") == "SUCCEEDED")
            allow_revision = day_is_published and (
                latest is None
                or latest.input_hash != input_hash
                or not _job_complete(latest)
            )
        window_start = datetime.strptime(review_date, "%Y-%m-%d").replace(tzinfo=UTC)
        window_end = window_start + timedelta(days=1)
        token = await self.persistence.begin_daily_review(
            review_date,
            window_start,
            window_end,
            owner=self.owner,
            lease_seconds=self.lease_seconds,
            allow_revision=allow_revision,
        )
        if token is None:
            latest = await self.jobs.latest(job_key)
            if latest is None:
                return PipelineResult(
                    review_date=review_date,
                    job_key=job_key,
                    revision=0,
                    idempotent=True,
                    stats_status=STAGE_PENDING,
                    review_status=STAGE_PENDING,
                    publish_status=STAGE_PENDING,
                    error_type="CLAIM_NOT_ACQUIRED",
                )
            return _result_from_row(latest, idempotent=True)

        job, idempotent = await self.jobs.claim(
            job_key=job_key,
            account_id=account_id,
            mode=mode,
            review_date=review_date,
            source_revision=source_revision,
            profile_version=profile_version,
            input_hash=input_hash,
            claim_token=token,
            owner=self.owner,
            lease_seconds=self.lease_seconds,
        )
        if idempotent:
            # Rare race: another worker completed the same revision between our
            # pre-check and our day-claim.  Restore the day claim to SUCCEEDED
            # with a deterministic read-only stats rerun; never leave it RUNNING.
            stats = await stats_runner()
            if stats.status == STAGE_SUCCEEDED:
                await self._save_day(review_date, stats, job, token)
                await self.persistence.heartbeat_daily_review(
                    review_date,
                    token,
                    owner=self.owner,
                    lease_seconds=self.lease_seconds,
                )
            else:
                await self.persistence.fail_daily_review(
                    review_date,
                    "IDEMPOTENT_RESTORE_FAILED",
                    stats.detail or "stats rerun failed",
                    claim_token=token,
                )
            return _result_from_row(job, idempotent=True)

        async def fence() -> bool:
            return await self.persistence.heartbeat_daily_review(
                review_date,
                token,
                owner=self.owner,
                lease_seconds=self.lease_seconds,
            )

        async def stage_update(stage: str, status: str, detail: str | None = None) -> bool:
            if status not in {STAGE_CLAIM_LOST} and not await fence():
                return False
            updated = await self.jobs.update_stage(
                job_id=job.id,
                stage=stage,
                status=status,
                claim_token=token,
                claim_owner=self.owner,
                claim_fence=job.claim_fence,
                lease_seconds=self.lease_seconds,
                detail=detail,
            )
            if updated:
                setattr(job, f"{stage}_status", status)
                if detail is not None:
                    job.last_error_type = stage.upper()
                    job.last_error_detail_sanitized = detail[:255]
            return updated

        # ---------------- stats stage ----------------
        try:
            stats = await stats_runner()
        except Exception as exc:
            stats = StageOutcome(STAGE_FAILED, detail=f"{type(exc).__name__}")
        if stats.status != STAGE_SUCCEEDED:
            await stage_update("stats", STAGE_FAILED, stats.detail or "stats failed")
            await self._fail_day(review_date, "STATS_FAILED", stats.detail or "", token)
            return _result_from_row(job, idempotent=False, stats=stats, error_type="STATS_FAILED")
        if not await stage_update("stats", STAGE_SUCCEEDED, None):
            await self.jobs.record_claim_lost(job_id=job.id, claim_token=token, owner=self.owner)
            await self._fail_day(review_date, "CLAIM_LOST", "stats stage", token)
            return _result_from_row(job, idempotent=False, stats=stats, error_type="CLAIM_LOST")

        # ---------------- review stage ----------------
        reviewed_count = 0
        review_failed = 0
        review_error: str | None = None
        publish_inputs: list[Any] = []
        if job.review_status != STAGE_SUCCEEDED:
            try:
                inputs = await review_inputs_loader()
            except Exception as exc:
                inputs = []
                review_error = f"REVIEW_INPUT_LOAD_FAILED:{type(exc).__name__}"
                review_failed = 1
            for item in inputs if review_error is None else []:
                try:
                    attempt = await review_runner(item)
                except Exception as exc:
                    attempt = None
                    review_error = f"REVIEW_RUNNER_EXCEPTION:{type(exc).__name__}"
                status = getattr(attempt, "status", None)
                if status == STAGE_SUCCEEDED:
                    reviewed_count += 1
                    publish_inputs.append(attempt)
                elif status == STAGE_CLAIM_LOST or (
                    getattr(attempt, "error_type", None) == "CLAIM_LOST"
                ):
                    review_error = "CLAIM_LOST"
                    break
                else:
                    review_failed += 1
                    publish_inputs.append(attempt)
                    review_error = getattr(attempt, "error_type", "REVIEW_FAILED")
            if review_error and review_error.startswith("REVIEW_INPUT_LOAD_FAILED"):
                await stage_update("review", STAGE_FAILED, review_error)
                await self._fail_day(
                    review_date, review_error.split(":", 1)[0], review_error, token
                )
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type=review_error
                )
            if review_error == "CLAIM_LOST":
                await self._record_claim_lost(job.id, token, job)
                await self._fail_day(review_date, "CLAIM_LOST", "review stage", token)
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
                )
            if review_failed:
                await stage_update("review", STAGE_PARTIAL, review_error or "REVIEW_FAILED")
                await self._fail_day(
                    review_date, "REVIEW_PARTIAL", review_error or "some reviews failed", token
                )
                return _result_from_row(
                    job,
                    idempotent=False,
                    stats=stats,
                    review_failed=review_failed,
                    error_type="REVIEW_PARTIAL",
                )
            if not await stage_update("review", STAGE_SUCCEEDED, None):
                await self._record_claim_lost(job.id, token, job)
                await self._fail_day(review_date, "CLAIM_LOST", "review publish", token)
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
                )
            reviewed_count = len(inputs)
        else:
            # Publish may be retried after a partial publish failure.  Reload
            # the durable SUCCEEDED attempts so the publisher never receives an
            # empty review list and marks the retry as successful.
            reloaded = await self.review_store.load_succeeded_for_date(
                review_date=review_date,
                profile_version=profile_version,
            )
            publish_inputs = list(reloaded)
            reviewed_count = len(reloaded)

        # ---------------- publish stage ----------------
        net_status = str(stats.payload.get("net_status", "UNKNOWN"))
        published_count = 0
        if not publish_inputs and net_status == "COMPLETE":
            # Defensive: publication with no review input is never a success.
            if not await stage_update(
                "publish", STAGE_SKIPPED_INCOMPLETE, "NO_PUBLISH_INPUT"
            ):
                await self._record_claim_lost(job.id, token, job)
                await self._fail_day(review_date, "CLAIM_LOST", "publish no-input", token)
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
                )
            await self._save_day(review_date, stats, job, token)
            final_job = await self.jobs.latest(job_key)
            return _result_from_row(
                final_job or job,
                idempotent=False,
                stats=stats,
                reviewed=reviewed_count,
            )
        if net_status != "COMPLETE":
            publish_status = STAGE_SKIPPED_INCOMPLETE
            detail = "net_status is not COMPLETE; reusable knowledge promotion blocked"
            if not await stage_update("publish", publish_status, detail):
                await self._record_claim_lost(job.id, token, job)
                await self._fail_day(review_date, "CLAIM_LOST", "publish skip", token)
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
                )
        elif job.publish_status != STAGE_SUCCEEDED:
            if not await fence():
                await self._record_claim_lost(job.id, token, job)
                await self._fail_day(review_date, "CLAIM_LOST", "before publish", token)
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
                )
            claim_guard = None
            build_guard = getattr(self.persistence, "build_claim_guard", None)
            if callable(build_guard):
                claim_guard = build_guard(
                    review_date, token, owner=self.owner, lease_seconds=self.lease_seconds
                )
            try:
                outcome = await _call_publisher(
                    publisher, stats, publish_inputs, fence=fence, claim_guard=claim_guard
                )
            except Exception as exc:
                outcome = StageOutcome(
                    STAGE_FAILED, detail=f"PUBLISH_EXCEPTION:{type(exc).__name__}"
                )
            if outcome.status != STAGE_SUCCEEDED:
                await stage_update("publish", STAGE_FAILED, outcome.detail or "publish failed")
                await self._fail_day(
                    review_date, "PUBLISH_FAILED", outcome.detail or "", token
                )
                return _result_from_row(
                    job,
                    idempotent=False,
                    stats=stats,
                    error_type="PUBLISH_FAILED",
                )
            published_count = int(outcome.payload.get("published_count", 0))
            if not await stage_update("publish", STAGE_SUCCEEDED, None):
                await self._record_claim_lost(job.id, token, job)
                await self._fail_day(review_date, "CLAIM_LOST", "publish commit", token)
                return _result_from_row(
                    job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
                )
        else:
            published_count = 0

        # ---------------- day publication ----------------
        saved = await self._save_day(review_date, stats, job, token)
        if not saved:
            await self.jobs.record_claim_lost(job_id=job.id, claim_token=token, owner=self.owner)
            return _result_from_row(
                job, idempotent=False, stats=stats, error_type="CLAIM_LOST"
            )
        final_job = await self.jobs.latest(job_key)
        return _result_from_row(
            final_job or job,
            idempotent=False,
            stats=stats,
            reviewed=reviewed_count,
            review_failed=review_failed,
            published=published_count,
        )

    # ------------------------------------------------------------------
    async def _save_day(self, review_date, stats: StageOutcome, job, token: str) -> bool:
        daily_stats = stats.payload.get("daily_stats")
        if daily_stats is None:
            return False
        output_ref = (
            f"growth:{review_date};rev={job.revision};stats={job.stats_status};"
            f"review={job.review_status};publish={job.publish_status}"
        )[:128]
        return await self.persistence.save_daily_review(
            review_date,
            daily_stats.for_storage(),
            episode_count=int(stats.payload.get("episode_count", 0)),
            output_ref=output_ref,
            claim_token=token,
        )

    async def _record_claim_lost(
        self, job_id: int, token: str, job: GrowthLearningJobORM | None = None
    ) -> None:
        await self.jobs.record_claim_lost(
            job_id=job_id, claim_token=token, owner=self.owner
        )
        if job is not None:
            job.last_error_type = "CLAIM_LOST"
            job.last_error_detail_sanitized = "claim token is no longer live"

    async def _fail_day(self, review_date: str, error_type: str, detail: str, token: str) -> None:
        await self.persistence.fail_daily_review(
            review_date, error_type, detail or error_type, claim_token=token
        )


def _result_from_row(
    row: GrowthLearningJobORM,
    *,
    idempotent: bool,
    stats: StageOutcome | None = None,
    reviewed: int = 0,
    review_failed: int = 0,
    published: int = 0,
    error_type: str | None = None,
) -> PipelineResult:
    return PipelineResult(
        review_date=row.review_date,
        job_key=row.job_key,
        revision=row.revision,
        idempotent=idempotent,
        stats_status=row.stats_status,
        review_status=row.review_status,
        publish_status=row.publish_status,
        net_status=str(stats.payload.get("net_status", "UNKNOWN")) if stats else "UNKNOWN",
        reviewed_count=reviewed,
        review_failed_count=review_failed,
        published_count=published,
        error_type=error_type or row.last_error_type,
        error_detail=row.last_error_detail_sanitized,
        claim_owner=row.claim_owner,
    )
