"""Round-2 correctness regressions: exact input/revision and durable failures.

Covers reviewer findings R02-R05 and required tests T02-T07.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.governance.daily_review import DailyReviewStats
from crypto_trader.learning.growth_models import (
    GrowthLearningJobORM,
    GrowthReviewAttemptORM,
    create_growth_schema,
)
from crypto_trader.learning.growth_pipeline import (
    STAGE_FAILED,
    STAGE_PENDING,
    STAGE_SUCCEEDED,
    GrowthJobStore,
    GrowthLearningPipeline,
    StageOutcome,
)
from crypto_trader.learning.growth_review import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    ReviewAttemptStore,
    StructuredReviewService,
)

REVIEW_DATE = "2026-09-09"
PROFILE = "profile-v1"


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


def _review_json(episode_id: str) -> dict:
    return {
        "schema_version": "growth-structured-review-v1",
        "episode_id": episode_id,
        "observation_facts": [
            {
                "statement": "Factual fill lineage exists.",
                "evidence_refs": [f"episode:{episode_id}"],
            }
        ],
        "candidate_explanations": [],
        "testable_lessons": [],
        "applicability_scope": {"scope": "SYMBOL_REGIME"},
        "uncertainty": "single case",
        "data_gaps": [],
        "risk_rule_changes": [],
    }


def _attempt_row(
    *,
    attempt_id: str,
    episode_id: str,
    account_id: str,
    mode: str,
    input_hash: str,
    job_key: str | None = None,
    job_revision: int | None = None,
) -> GrowthReviewAttemptORM:
    return GrowthReviewAttemptORM(
        attempt_id=attempt_id,
        review_date=REVIEW_DATE,
        episode_id=episode_id,
        account_id=account_id,
        mode=mode,
        symbol="BTCUSDT",
        direction="LONG",
        profile_version=PROFILE,
        prompt_version="prompt-v1",
        schema_version="growth-structured-review-v1",
        provider="fake",
        model="fake-model",
        prompt_hash="ph",
        schema_hash="sh",
        input_hash=input_hash,
        status=STATUS_SUCCEEDED,
        attempt_no=1,
        result_json=_review_json(episode_id),
        usage_status="KNOWN",
        job_key=job_key,
        job_revision=job_revision,
    )


async def test_recovery_filters_wrong_account_mode_and_input_hash(growth_db):
    async with growth_db.session_factory() as session:
        session.add_all(
            [
                _attempt_row(
                    attempt_id="a1",
                    episode_id="ep-a",
                    account_id="A",
                    mode="PAPER",
                    input_hash="hash-A",
                ),
                _attempt_row(
                    attempt_id="b1",
                    episode_id="ep-b",
                    account_id="B",
                    mode="PAPER",
                    input_hash="hash-A",
                ),
                _attempt_row(
                    attempt_id="a2",
                    episode_id="ep-a",
                    account_id="A",
                    mode="LIVE",
                    input_hash="hash-A",
                ),
                _attempt_row(
                    attempt_id="a3",
                    episode_id="ep-a",
                    account_id="A",
                    mode="PAPER",
                    input_hash="hash-B",
                ),
            ]
        )
        await session.commit()

    store = ReviewAttemptStore(growth_db.session_factory)
    exact = await store.load_succeeded_for_date(
        review_date=REVIEW_DATE,
        profile_version=PROFILE,
        account_id="A",
        mode="PAPER",
        input_hash="hash-A",
    )
    assert [row.attempt_id for row in exact] == ["a1"]

    wrong_account = await store.load_succeeded_for_date(
        review_date=REVIEW_DATE,
        profile_version=PROFILE,
        account_id="C",
        mode="PAPER",
        input_hash="hash-A",
    )
    assert wrong_account == []
    wrong_mode = await store.load_succeeded_for_date(
        review_date=REVIEW_DATE,
        profile_version=PROFILE,
        account_id="A",
        mode="SHADOW",
        input_hash="hash-A",
    )
    assert wrong_mode == []


async def test_recovery_prefers_exact_job_revision(growth_db):
    async with growth_db.session_factory() as session:
        session.add_all(
            [
                _attempt_row(
                    attempt_id="rev1",
                    episode_id="ep-1",
                    account_id="A",
                    mode="PAPER",
                    input_hash="hash-A",
                    job_key="job-x",
                    job_revision=1,
                ),
                _attempt_row(
                    attempt_id="rev2",
                    episode_id="ep-1",
                    account_id="A",
                    mode="PAPER",
                    input_hash="hash-A",
                    job_key="job-x",
                    job_revision=2,
                ),
            ]
        )
        await session.commit()
    store = ReviewAttemptStore(growth_db.session_factory)
    rows = await store.load_succeeded_for_date(
        review_date=REVIEW_DATE,
        profile_version=PROFILE,
        account_id="A",
        mode="PAPER",
        input_hash="hash-A",
        job_key="job-x",
        job_revision=2,
    )
    assert [row.attempt_id for row in rows] == ["rev2"]


async def test_changed_incomplete_input_opens_new_clean_revision(growth_db):
    store = GrowthJobStore(growth_db.session_factory)
    first, _ = await store.claim(
        job_key="job-change",
        account_id="A",
        mode="PAPER",
        review_date=REVIEW_DATE,
        source_revision="src-1",
        profile_version=PROFILE,
        input_hash="hash-A",
        claim_token="token-1",
        owner="worker",
        lease_seconds=60,
    )
    await store.update_stage(
        job_id=first.id,
        stage="stats",
        status=STAGE_SUCCEEDED,
        claim_token="token-1",
        claim_owner="worker",
        claim_fence=first.claim_fence,
        lease_seconds=60,
    )
    await store.update_stage(
        job_id=first.id,
        stage="review",
        status=STAGE_FAILED,
        claim_token="token-1",
        claim_owner="worker",
        claim_fence=first.claim_fence,
        lease_seconds=60,
        detail="PROVIDER_TIMEOUT",
    )

    second, idempotent = await store.claim(
        job_key="job-change",
        account_id="A",
        mode="PAPER",
        review_date=REVIEW_DATE,
        source_revision="src-2",
        profile_version=PROFILE,
        input_hash="hash-B",
        claim_token="token-2",
        owner="worker",
        lease_seconds=60,
    )
    assert idempotent is False
    assert second.revision == 2
    assert second.input_hash == "hash-B"
    assert second.stats_status == STAGE_PENDING
    assert second.review_status == STAGE_PENDING
    assert second.publish_status == STAGE_PENDING

    async with growth_db.session_factory() as session:
        old = (
            await session.execute(
                select(GrowthLearningJobORM).where(GrowthLearningJobORM.id == first.id)
            )
        ).scalar_one()
    assert old.revision == 1
    assert old.input_hash == "hash-A"
    assert old.stats_status == STAGE_SUCCEEDED
    assert old.review_status == STAGE_FAILED
    assert old.superseded_by_revision == 2


async def test_complete_input_with_zero_publish_input_is_blocked(growth_db):
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")

    async def stats():
        return StageOutcome(
            STAGE_SUCCEEDED,
            payload={
                "net_status": "COMPLETE",
                "episode_count": 0,
                "daily_stats": DailyReviewStats(
                    date=REVIEW_DATE, daily_pnl=Decimal("0"), net_pnl=Decimal("0")
                ),
            },
        )

    async def loader():
        return []

    async def runner(item):  # pragma: no cover - loader returns none
        return item

    class Publisher:
        async def __call__(self, stats_arg, reviews, *, fence):
            raise AssertionError("publisher must not be called without input")

    result = await pipeline.run_day(
        review_date=REVIEW_DATE,
        account_id="A",
        mode="PAPER",
        source_revision="src-1",
        profile_version=PROFILE,
        input_hash="hash-A",
        stats_runner=stats,
        review_inputs_loader=loader,
        review_runner=runner,
        publisher=Publisher(),
    )
    assert result.succeeded is False
    assert result.error_type == "BLOCKED_NO_PUBLISH_INPUT"
    assert result.publish_status == STAGE_FAILED
    row = await GrowthJobStore(growth_db.session_factory).latest("job-change")
    # latest() is keyed by the exact identity; fetch this job explicitly.
    async with growth_db.session_factory() as session:
        row = (
            await session.execute(
                select(GrowthLearningJobORM).where(
                    GrowthLearningJobORM.job_key == result.job_key
                )
            )
        ).scalar_one()
    assert row.publish_status == STAGE_FAILED


class _RaisingProvider:
    name = "fake-provider"
    model = "fake-model"

    async def complete_json(self, **kwargs):
        raise TimeoutError("SECRET-CANARY")


def _episode_input():
    from crypto_trader.learning.growth_contracts import EpisodeReviewInput

    now = datetime(2026, 9, 9, 12, tzinfo=UTC)
    return EpisodeReviewInput(
        episode_id="ep-provider-exc",
        account_id="A",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        funding_provenance="PROVEN",
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        opened_at=now,
        closed_at=now,
        entry_market_regime="BULL",
        terminal_reason="EXIT",
    )


async def test_provider_exception_leaves_one_failed_unknown_attempt(growth_db):
    service = StructuredReviewService(
        _RaisingProvider(), growth_db.session_factory, retries=0
    )
    review_input = _episode_input()
    attempt = await service.review(
        review_input,
        review_date=REVIEW_DATE,
        allowed_refs=review_input.derived_refs(),
    )
    assert attempt.status == STATUS_FAILED
    assert attempt.usage_status == "UNKNOWN"
    async with growth_db.session_factory() as session:
        rows = (
            await session.execute(
                select(GrowthReviewAttemptORM).where(
                    GrowthReviewAttemptORM.episode_id == "ep-provider-exc"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.status == STATUS_FAILED
    assert row.usage_status == "UNKNOWN"
    assert row.result_json is None
    serialized = " ".join(
        str(value) for value in (row.error_type, row.error_detail_sanitized)
    )
    assert "SECRET-CANARY" not in serialized
