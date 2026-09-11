"""Round-2 publication/version/proposition regressions (R01, R06-R08).

Required tests T01, T08-T12.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from crypto_trader.learning.growth_contracts import (
    ObservationFact,
    StructuredReview,
)
from crypto_trader.learning.growth_contracts import (
    TestableLesson as LessonSpec,
)
from crypto_trader.learning.growth_experience import ClaimLostError
from crypto_trader.learning.growth_knowledge import (
    PATTERN_CANDIDATE,
    PATTERN_CONTESTED,
    PATTERN_EXPIRED,
    PATTERN_REVOKED,
    PATTERN_VALIDATED,
    RETRIEVABLE_STATUSES,
    EpisodeBinding,
    GrowthKnowledgePublisher,
)
from crypto_trader.learning.growth_models import (
    GrowthPatternORM,
    create_growth_schema,
)
from crypto_trader.learning.growth_review import STATUS_SUCCEEDED, ReviewAttempt
from crypto_trader.persistence.models import DailyReviewRunORM

SYMBOL = "BTCUSDT"
REGIME = "TREND"
DIRECTION = "LONG"
DATE = "2026-09-09"
KNOWN_AT = datetime(2026, 9, 9, 12, tzinfo=UTC)
STATEMENT_A = "Rising volume at entry is associated with trend continuation."
STATEMENT_B = "High funding with rising open interest precedes crowding risk."


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


@pytest.fixture
def publisher(growth_db):
    return GrowthKnowledgePublisher(growth_db.session_factory, min_pattern_samples=3)


def _binding() -> EpisodeBinding:
    return EpisodeBinding(
        account_id="default",
        mode="PAPER",
        currency="USDT",
        instrument_id=SYMBOL,
        source_revision="src-df55b11",
        terminal_reason="EXIT",
        regime=REGIME,
        direction=DIRECTION,
    )


def _attempt(
    episode_id: str,
    *,
    statement: str = STATEMENT_A,
    contrary_refs: list[str] | None = None,
) -> ReviewAttempt:
    lesson = LessonSpec(
        statement=statement,
        testable_prediction="Future comparable episodes show the same association.",
        scope={"scope": "SYMBOL_REGIME", "symbols": [SYMBOL], "regimes": [REGIME]},
        evidence_refs=[f"episode:{episode_id}"],
        contrary_refs=contrary_refs or [],
        uncertainty="candidate",
        confidence="LOW",
    )
    review = StructuredReview(
        episode_id=episode_id,
        observation_facts=[
            ObservationFact(
                statement="The episode closed with complete fills.",
                evidence_refs=[f"episode:{episode_id}"],
            )
        ],
        testable_lessons=[lesson],
        applicability_scope={
            "scope": "SYMBOL_REGIME",
            "symbols": [SYMBOL],
            "regimes": [REGIME],
        },
    )
    return ReviewAttempt(
        status=STATUS_SUCCEEDED,
        attempt_id=f"attempt_{episode_id}",
        review=review,
        account_id="default",
        mode="PAPER",
        symbol=SYMBOL,
        direction=DIRECTION,
        regime=REGIME,
        currency="USDT",
        review_date=DATE,
        input_hash=f"input_{episode_id}",
    )


async def _visible_patterns(publisher, *, as_of: datetime):
    return await publisher.store.current_patterns_for_scope(
        account_id="default",
        mode="PAPER",
        symbol=SYMBOL,
        regime=REGIME,
        direction=DIRECTION,
        statuses=RETRIEVABLE_STATUSES,
        as_of=as_of,
    )


async def test_t01_stale_claim_cannot_publish_reviewable_knowledge(growth_db, publisher):
    attempts = [_attempt(f"stale_{index}") for index in range(3)]
    bindings = {attempt.review.episode_id: _binding() for attempt in attempts}
    async with growth_db.session_factory() as session:
        session.add(
            DailyReviewRunORM(
                review_date=DATE,
                status="RUNNING",
                claim_token="stale-token",
                owner="worker",
                claim_deadline_at=KNOWN_AT - timedelta(seconds=1),
                attempt_count=1,
            )
        )
        await session.commit()

    with pytest.raises(ClaimLostError):
        await publisher.publish_attempts(
            attempts,
            bindings=bindings,
            known_at=KNOWN_AT,
            claim_context=(DATE, "stale-token", "worker"),
        )

    visible = await _visible_patterns(publisher, as_of=datetime.now(UTC))
    assert visible == []
    async with growth_db.session_factory() as session:
        statuses = (
            await session.execute(select(GrowthPatternORM.status))
        ).scalars().all()
    assert PATTERN_VALIDATED not in statuses
    assert PATTERN_CONTESTED not in statuses


async def test_t08_revoked_latest_pattern_cannot_resurrect_old_validated(
    growth_db, publisher
):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"revoke_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert pattern.status == PATTERN_VALIDATED
    revoke_at = KNOWN_AT + timedelta(hours=1)
    await publisher.revoke(
        kind="pattern", logical_id=pattern.pattern_id, reason="R07_TEST", at=revoke_at
    )
    assert await _visible_patterns(publisher, as_of=revoke_at + timedelta(seconds=1)) == []
    historical = await _visible_patterns(
        publisher, as_of=revoke_at - timedelta(seconds=1)
    )
    assert [row.status for row in historical] == [PATTERN_VALIDATED]


async def test_t09_compression_cannot_use_revoked_latest_pattern(
    growth_db, publisher
):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"compress_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    revoke_at = KNOWN_AT + timedelta(hours=1)
    await publisher.revoke(
        kind="pattern", logical_id=pattern.pattern_id, reason="COMPRESS_REVOKE", at=revoke_at
    )
    compression = await publisher.compress(
        account_id="default",
        mode="PAPER",
        symbol=SYMBOL,
        regime=REGIME,
        direction=DIRECTION,
        min_samples=3,
        known_at=revoke_at + timedelta(seconds=1),
    )
    assert compression is None


async def test_t10_t11_revoke_and_expire_use_transition_time(growth_db, publisher):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"time_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    revoke_at = KNOWN_AT + timedelta(hours=1)
    revoked = await publisher.revoke(
        kind="pattern", logical_id=pattern.pattern_id, reason="TIME_REVOKE", at=revoke_at
    )
    assert revoked.known_at == revoke_at
    assert revoked.status == PATTERN_REVOKED
    assert received_original(pattern) == KNOWN_AT

    expire_at = revoke_at + timedelta(hours=1)
    expired = await publisher.expire(
        kind="pattern", logical_id=pattern.pattern_id, valid_until=expire_at
    )
    assert expired.known_at == expire_at
    assert expired.status == PATTERN_EXPIRED
    before = await _visible_patterns(
        publisher, as_of=expire_at - timedelta(seconds=1)
    )
    assert before == []
    after = await _visible_patterns(publisher, as_of=expire_at + timedelta(seconds=1))
    assert after == []


def received_original(pattern: GrowthPatternORM) -> datetime:
    known = pattern.known_at
    if known.tzinfo is None:
        known = known.replace(tzinfo=UTC)
    return known


async def test_t12_different_propositions_do_not_validate_each_other(
    growth_db, publisher
):
    for index in range(2):
        await publisher.publish_review(
            attempt=_attempt(f"prop_a_{index}", statement=STATEMENT_A),
            binding=_binding(),
            known_at=KNOWN_AT,
        )
    await publisher.publish_review(
        attempt=_attempt("prop_b_0", statement=STATEMENT_B),
        binding=_binding(),
        known_at=KNOWN_AT,
    )
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert len(patterns) == 2
    by_count = {row.sample_count: row for row in patterns}
    assert by_count[2].status == PATTERN_CANDIDATE
    assert by_count[1].status == PATTERN_CANDIDATE
    assert by_count[1].support_grade == "INSUFFICIENT"

    third = await publisher.publish_review(
        attempt=_attempt("prop_a_2", statement=STATEMENT_A),
        binding=_binding(),
        known_at=KNOWN_AT,
    )
    assert third.pattern_status == PATTERN_VALIDATED
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    a = [row for row in patterns if row.sample_count == 3][0]
    b = [row for row in patterns if row.sample_count == 1][0]
    assert a.status == PATTERN_VALIDATED
    assert b.status == PATTERN_CANDIDATE
