"""G-BLOCKER-1 adversarial test: a lost claim cannot publish retrievable knowledge.

Scenario (mandated by the review):

    worker A claims the day
    the claim expires
    worker B takes ownership
    worker A attempts to publish

Expected:

    A cannot commit retrievable knowledge (its publish transaction rolls back)
    B remains the authoritative owner of the day

The test drives the REAL publisher with the REAL in-transaction claim guard, so
it proves atomicity rather than the pre-publish fence check alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.learning.growth_knowledge import (
    EpisodeBinding,
    GrowthKnowledgePublisher,
    GrowthLessonORM,
    GrowthPatternORM,
)
from crypto_trader.learning.growth_pipeline import (
    STAGE_CLAIM_LOST,
    STAGE_SUCCEEDED,
)
from crypto_trader.persistence.models import DailyReviewRunORM
from tests.growth_system.test_knowledge_revision import (
    DIRECTION,
    REGIME,
    SYMBOL,
    _attempt,
)

REVIEW_DATE = "2026-09-09"
OWNER_A = "worker-a"
OWNER_B = "worker-b"


async def _claim(persistence: MemoryPersistence, owner: str) -> str:
    start = datetime.strptime(REVIEW_DATE, "%Y-%m-%d").replace(tzinfo=UTC)
    token = await persistence.begin_daily_review(
        REVIEW_DATE,
        start,
        start + timedelta(days=1),
        owner=owner,
        lease_seconds=300,
        allow_revision=True,
    )
    assert token is not None
    return token


async def _expire(database) -> None:
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == REVIEW_DATE)
            )
        ).scalar_one()
        row.claim_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def _count_published(database) -> tuple[int, int]:
    async with database.session_factory() as session:
        lessons = len((await session.scalars(select(GrowthLessonORM))).all())
        patterns = len((await session.scalars(select(GrowthPatternORM))).all())
    return lessons, patterns


async def _binding() -> EpisodeBinding:
    return EpisodeBinding(
        account_id="default",
        mode="PAPER",
        currency="USDT",
        instrument_id=SYMBOL,
        source_revision="src-test",
        funding_provenance="PROVEN",
        direction=DIRECTION,
        regime=REGIME,
        proof_kind="FACTUAL_EPISODE",
    )


@pytest.fixture
async def growth_db(database):
    from crypto_trader.learning.growth_models import create_growth_schema

    await create_growth_schema(database.engine)
    return database


async def test_lost_claim_cannot_commit_retrievable_knowledge(growth_db):
    persistence = MemoryPersistence(growth_db.session_factory)
    token_a = await _claim(persistence, OWNER_A)

    # A's claim expires and B takes over the same day.
    await _expire(growth_db)
    token_b = await _claim(persistence, OWNER_B)
    assert token_b != token_a

    # A wakes up and attempts to publish with ITS OWN (now stale) guard.
    guard_a = persistence.build_claim_guard(
        REVIEW_DATE, token_a, owner=OWNER_A, lease_seconds=300
    )
    publisher = GrowthKnowledgePublisher(
        growth_db.session_factory, min_pattern_samples=1, claim_guard=guard_a
    )
    outcome = await publisher.as_pipeline_publisher({})(
        None, [_attempt("episode_a1")], fence=_always_true, claim_guard=guard_a
    )

    assert outcome.status == STAGE_CLAIM_LOST
    assert "rolled back" in (outcome.detail or "") or "claim lost" in (outcome.detail or "")

    # Nothing A tried to write is retrievable.
    lessons, patterns = await _count_published(growth_db)
    assert (lessons, patterns) == (0, 0)

    # B remains authoritative.
    async with growth_db.session_factory() as session:
        row = (
            await session.execute(
                select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == REVIEW_DATE)
            )
        ).scalar_one()
    assert row.claim_token == token_b
    assert row.owner == OWNER_B


async def test_stale_guard_rolls_back_each_write_and_current_claim_still_publishes(growth_db):
    """Control: the CURRENT claim's guard commits normally."""
    persistence = MemoryPersistence(growth_db.session_factory)
    token = await _claim(persistence, OWNER_A)
    guard = persistence.build_claim_guard(
        REVIEW_DATE, token, owner=OWNER_A, lease_seconds=300
    )
    publisher = GrowthKnowledgePublisher(
        growth_db.session_factory, min_pattern_samples=1, claim_guard=guard
    )
    outcome = await publisher.as_pipeline_publisher({})(
        None, [_attempt("episode_ok")], fence=_always_true, claim_guard=guard
    )

    assert outcome.status == STAGE_SUCCEEDED, outcome.detail
    lessons, patterns = await _count_published(growth_db)
    assert lessons >= 1
    assert patterns >= 1


async def _always_true() -> bool:
    return True


async def test_fence_that_passed_before_expiry_is_not_sufficient_alone(growth_db):
    """Documents the historical leak: a fence sampled BEFORE the commit is TOCTOU.

    The pre-fix publisher only called ``fence()`` once and then committed, so a
    claim that expired inside that window still published retrievable knowledge.
    This test simulates that window (the fence callable reports True) with the
    claim already owned by worker B, and asserts that the in-transaction guard is
    what actually prevents the publication.
    """
    persistence = MemoryPersistence(growth_db.session_factory)
    token_a = await _claim(persistence, OWNER_A)
    await _expire(growth_db)
    token_b = await _claim(persistence, OWNER_B)
    assert token_b != token_a

    guard_a = persistence.build_claim_guard(
        REVIEW_DATE, token_a, owner=OWNER_A, lease_seconds=300
    )
    publisher = GrowthKnowledgePublisher(
        growth_db.session_factory, min_pattern_samples=1, claim_guard=guard_a
    )

    async def stale_fence_still_reports_true() -> bool:
        # worst case: the pre-commit fence sample happened before the takeover
        return True

    outcome = await publisher.as_pipeline_publisher({})(
        None,
        [_attempt("episode_toctou")],
        fence=stale_fence_still_reports_true,
        claim_guard=guard_a,
    )
    assert outcome.status == STAGE_CLAIM_LOST
    assert await _count_published(growth_db) == (0, 0)
