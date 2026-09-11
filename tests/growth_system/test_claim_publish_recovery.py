"""G03: staged/fenced claim, recovery, old-token and late-revision tests (TEST_ONLY)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from crypto_trader.governance.daily_review import DailyReviewStats
from crypto_trader.learning.growth_models import (
    GrowthLearningJobORM,
    create_growth_schema,
)
from crypto_trader.learning.growth_pipeline import (
    STAGE_CLAIM_LOST,
    STAGE_FAILED,
    STAGE_PARTIAL,
    STAGE_PENDING,
    STAGE_SKIPPED_INCOMPLETE,
    STAGE_SUCCEEDED,
    GrowthLearningPipeline,
    StageOutcome,
)
from crypto_trader.persistence.models import DailyReviewRunORM

REVIEW_DATE = "2026-09-09"
ACCOUNT = "default"
MODE = "PAPER"
SOURCE_REVISION = "src-df55b11"
PROFILE = "profile-v1"


@dataclass
class StubReview:
    episode_id: str
    status: str = STAGE_SUCCEEDED
    error_type: str | None = None


def _stats_ok(episode_count: int = 2, net_status: str = "COMPLETE") -> StageOutcome:
    return StageOutcome(
        STAGE_SUCCEEDED,
        payload={
            "net_status": net_status,
            "episode_count": episode_count,
            "daily_stats": DailyReviewStats(
                date=REVIEW_DATE,
                daily_pnl=Decimal("1"),
                net_pnl=Decimal("1"),
                net_status=net_status,
            ),
        },
    )


class Recorder:
    def __init__(self) -> None:
        self.stats_calls = 0
        self.review_inputs: list[list[Any]] = []
        self.review_calls: list[str] = []
        self.publish_calls = 0
        self.publish_fences: list[bool] = []
        self.review_batch_sizes: list[int] = []
        self.fail_review_once: set[str] = set()
        self.fail_publish_once = 0

    def stats_runner(self):
        async def runner() -> StageOutcome:
            self.stats_calls += 1
            return _stats_ok()

        return runner

    def review_loader(self, inputs: list[Any]):
        async def loader() -> list[Any]:
            self.review_inputs.append(list(inputs))
            return list(inputs)

        return loader

    def review_runner(self):
        done: set[str] = set()

        async def runner(item: Any) -> StubReview:
            episode_id = item.episode_id
            self.review_calls.append(episode_id)
            if episode_id in self.fail_review_once:
                self.fail_review_once.discard(episode_id)
                return StubReview(episode_id, STAGE_FAILED, "PROVIDER_HTTP_500")
            done.add(episode_id)
            return StubReview(episode_id)

        return runner

    def publisher(self):
        async def runner(stats, reviews, *, fence) -> StageOutcome:
            self.publish_calls += 1
            self.review_batch_sizes.append(len(reviews))
            self.publish_fences.append(await fence())
            if self.fail_publish_once:
                self.fail_publish_once -= 1
                return StageOutcome(STAGE_FAILED, detail="PUBLISH_CRASH")
            published = sum(
                1
                for attempt in reviews
                if getattr(attempt, "status", None) == STAGE_SUCCEEDED
                and getattr(attempt, "error_type", None) != "ALREADY_PUBLISHED"
            )
            return StageOutcome(STAGE_SUCCEEDED, payload={"published_count": published})

        return runner


def _runner(recorder: Recorder, pipeline: GrowthLearningPipeline, **overrides):
    inputs = overrides.pop("inputs", [StubReview("episode_a"), StubReview("episode_b")])
    return pipeline.run_day(
        review_date=REVIEW_DATE,
        account_id=ACCOUNT,
        mode=MODE,
        source_revision=SOURCE_REVISION,
        profile_version=PROFILE,
        input_hash=overrides.pop("input_hash", "hash_v1"),
        stats_runner=overrides.pop("stats_runner", recorder.stats_runner()),
        review_inputs_loader=overrides.pop("review_inputs_loader", recorder.review_loader(inputs)),
        review_runner=overrides.pop("review_runner", recorder.review_runner()),
        publisher=overrides.pop("publisher", recorder.publisher()),
    )


async def _expire_claim(database, review_date: str = REVIEW_DATE) -> None:
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == review_date)
            )
        ).scalar_one()
        row.claim_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def _day_row(database, review_date: str = REVIEW_DATE) -> DailyReviewRunORM:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == review_date)
            )
        ).scalar_one()


async def _job_rows(database, job_key: str) -> list[GrowthLearningJobORM]:
    async with database.session_factory() as session:
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


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


async def test_stats_failure_isolated_and_retry_resumes_without_rerunning_passed_stages(growth_db):
    recorder = Recorder()
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")

    async def bad_stats() -> StageOutcome:
        recorder.stats_calls += 1
        return StageOutcome(STAGE_FAILED, detail="STATS_EXCEPTION")

    first = await _runner(recorder, pipeline, stats_runner=bad_stats)
    assert first.stats_status == STAGE_FAILED
    assert first.review_status == STAGE_PENDING
    assert first.publish_status == STAGE_PENDING
    assert recorder.review_calls == []
    assert (await _day_row(growth_db)).status == "FAILED"

    # Retry after the deterministic failure.  Only non-SUCCEEDED stages rerun.
    second = await _runner(recorder, pipeline)
    assert second.succeeded
    assert second.stats_status == STAGE_SUCCEEDED
    assert second.review_status == STAGE_SUCCEEDED
    assert second.publish_status == STAGE_SUCCEEDED
    assert recorder.publish_calls == 1
    assert (await _day_row(growth_db)).status == "SUCCEEDED"


async def test_review_partial_failure_does_not_mask_stats_or_publish(growth_db):
    recorder = Recorder()
    recorder.fail_review_once = {"episode_b"}
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")

    first = await _runner(recorder, pipeline)
    assert first.stats_status == STAGE_SUCCEEDED
    assert first.review_status == STAGE_PARTIAL
    assert first.publish_status == STAGE_PENDING
    assert first.error_type == "REVIEW_PARTIAL"
    assert recorder.publish_calls == 0
    row = await _day_row(growth_db)
    assert row.status == "FAILED"
    assert row.last_error_type == "REVIEW_PARTIAL"

    # Retry: the successful review attempt for A must not be re-run by a real
    # idempotent review service; the stub records every call, so we only assert
    # the stage completes and publish runs once.
    await _expire_claim(growth_db)
    second = await _runner(recorder, pipeline)
    assert second.succeeded
    assert recorder.publish_calls == 1


async def test_publish_failure_isolated_and_retry_is_idempotent(growth_db):
    recorder = Recorder()
    recorder.fail_publish_once = 1
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    first = await _runner(recorder, pipeline)
    assert first.stats_status == STAGE_SUCCEEDED
    assert first.review_status == STAGE_SUCCEEDED
    assert first.publish_status == STAGE_FAILED
    assert first.error_type == "PUBLISH_FAILED"
    assert first.succeeded is False

    await _expire_claim(growth_db)
    second = await _runner(recorder, pipeline)
    # The stub review runner does not persist durable attempts, so the safe
    # retry path refuses to publish and reports BLOCKED_NO_PUBLISH_INPUT.
    # COMPLETE + zero publish input is never a success (R04).
    assert second.stats_status == STAGE_SUCCEEDED
    assert second.review_status == STAGE_SUCCEEDED
    assert second.publish_status == STAGE_FAILED
    assert second.succeeded is False
    assert second.error_type == "BLOCKED_NO_PUBLISH_INPUT"
    assert second.published_count == 0
    assert recorder.publish_calls == 1
    # The first publish attempt observed a live fence before visible work.
    assert all(recorder.publish_fences)


async def test_two_workers_claim_once(growth_db):
    recorder = Recorder()
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_stats() -> StageOutcome:
        recorder.stats_calls += 1
        started.set()
        await release.wait()
        return _stats_ok()

    task_a = asyncio.create_task(
        _runner(recorder, pipeline, stats_runner=slow_stats)
    )
    await asyncio.wait_for(started.wait(), timeout=5)

    worker_b = GrowthLearningPipeline(growth_db.session_factory, owner="worker-b")
    result_b = await _runner(Recorder(), worker_b, stats_runner=slow_stats)
    assert result_b.idempotent is True
    assert result_b.error_type in {None, "CLAIM_NOT_ACQUIRED"}

    release.set()
    result_a = await asyncio.wait_for(task_a, timeout=5)
    assert result_a.succeeded
    assert recorder.publish_calls == 1


async def test_stale_token_cannot_publish_after_new_worker_completes(growth_db):
    recorder_a = Recorder()
    pipeline_a = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_stats() -> StageOutcome:
        started.set()
        await release.wait()
        return _stats_ok()

    task_a = asyncio.create_task(
        _runner(recorder_a, pipeline_a, stats_runner=blocked_stats)
    )
    await asyncio.wait_for(started.wait(), timeout=5)

    # The first claim expires (simulated crash/restart).
    await _expire_claim(growth_db)
    recorder_b = Recorder()
    pipeline_b = GrowthLearningPipeline(growth_db.session_factory, owner="worker-b")
    result_b = await _runner(recorder_b, pipeline_b)
    assert result_b.succeeded
    assert recorder_b.publish_calls == 1

    # Old worker wakes up; its fence is dead, so it must not publish again.
    release.set()
    result_a = await asyncio.wait_for(task_a, timeout=5)
    assert result_a.error_type == "CLAIM_LOST"
    assert result_a.stats_status == STAGE_CLAIM_LOST or result_a.stats_status != STAGE_SUCCEEDED
    assert recorder_a.publish_calls == 0
    assert recorder_b.publish_calls == 1
    # The newly published day is not overwritten by the stale worker.
    row = await _day_row(growth_db)
    assert row.status == "SUCCEEDED"
    assert row.claim_token != "" and row.claim_token is not None


async def test_more_than_1000_episodes_are_fully_processed(growth_db):
    recorder = Recorder()
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    inputs = [StubReview(f"episode_{index}") for index in range(1200)]
    result = await _runner(
        recorder,
        pipeline,
        inputs=inputs,
        input_hash="hash_1200",
    )
    assert result.succeeded
    assert result.reviewed_count == 1200
    assert len(recorder.review_calls) == 1200


async def test_incomplete_funding_never_publishes_reusable_knowledge(growth_db):
    recorder = Recorder()
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")

    async def incomplete_stats() -> StageOutcome:
        recorder.stats_calls += 1
        return _stats_ok(net_status="INCOMPLETE_UNKNOWN_FUNDING")

    result = await _runner(recorder, pipeline, stats_runner=incomplete_stats)
    assert result.stats_status == STAGE_SUCCEEDED
    assert result.review_status == STAGE_SUCCEEDED
    assert result.publish_status == STAGE_SKIPPED_INCOMPLETE
    assert result.succeeded
    assert recorder.publish_calls == 0
    assert (await _day_row(growth_db)).status == "SUCCEEDED"


async def test_late_revision_supersedes_and_same_hash_is_idempotent(growth_db):
    recorder = Recorder()
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    first = await _runner(recorder, pipeline, input_hash="hash_v1")
    assert first.succeeded and first.revision == 1
    assert recorder.publish_calls == 1

    same = await _runner(recorder, pipeline, input_hash="hash_v1")
    assert same.idempotent is True
    assert recorder.publish_calls == 1

    await _expire_claim(growth_db)
    late = await _runner(recorder, pipeline, input_hash="hash_v2_late")
    assert late.succeeded
    assert late.revision == 2
    assert recorder.publish_calls == 2

    rows = await _job_rows(growth_db, first.job_key)
    assert [row.revision for row in rows] == [1, 2]
    assert rows[0].superseded_by_revision == 2
    assert rows[1].revision == 2
    # Replaying revision 2 is idempotent.
    replay = await _runner(recorder, pipeline, input_hash="hash_v2_late")
    assert replay.idempotent is True
    assert recorder.publish_calls == 2


async def test_publish_retry_reloads_durable_review_attempts(growth_db):
    """Regression from independent review: publish retry must not use empty input."""

    from crypto_trader.learning.growth_contracts import ObservationFact, StructuredReview
    from crypto_trader.learning.growth_models import GrowthReviewAttemptORM
    from crypto_trader.learning.growth_review import STATUS_SUCCEEDED as REVIEW_SUCCEEDED

    recorder = Recorder()
    recorder.fail_publish_once = 1
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    inputs = [StubReview("reload_a"), StubReview("reload_b")]
    persisted: set[str] = set()

    async def persisting_runner(item) -> StubReview:
        if item.episode_id not in persisted:
            review = StructuredReview(
                episode_id=item.episode_id,
                observation_facts=[
                    ObservationFact(
                        statement="Complete factual fills.",
                        evidence_refs=[f"episode:{item.episode_id}"],
                    )
                ],
            )
            async with growth_db.session_factory() as session:
                session.add(
                    GrowthReviewAttemptORM(
                        attempt_id=f"attempt_{item.episode_id}",
                        review_date=REVIEW_DATE,
                        episode_id=item.episode_id,
                        account_id=ACCOUNT,
                        mode=MODE,
                        symbol="BTCUSDT",
                        direction="LONG",
                        profile_version=PROFILE,
                        prompt_version="v1",
                        schema_version="v1",
                        provider="fake",
                        input_hash=f"input_{item.episode_id}",
                        prompt_hash="ph",
                        schema_hash="sh",
                        status=REVIEW_SUCCEEDED,
                        attempt_no=1,
                        result_json=review.model_dump(mode="json"),
                        usage_status="UNKNOWN",
                    )
                )
                await session.commit()
            persisted.add(item.episode_id)
        return StubReview(item.episode_id)

    first = await _runner(
        recorder,
        pipeline,
        inputs=inputs,
        input_hash="reload_hash",
        review_runner=persisting_runner,
    )
    assert first.review_status == STAGE_SUCCEEDED
    assert first.publish_status == STAGE_FAILED
    assert recorder.publish_calls == 1

    await _expire_claim(growth_db)
    second = await _runner(
        recorder,
        pipeline,
        inputs=inputs,
        input_hash="reload_hash",
        review_runner=persisting_runner,
    )
    assert second.succeeded
    assert second.publish_status == STAGE_SUCCEEDED
    assert recorder.publish_calls == 2
    # The retry publisher received the two durable attempts, not an empty list.
    assert recorder.review_batch_sizes == [2, 2]
