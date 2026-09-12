"""G04: evidence grading, contradiction revisions, revocation, compression (TEST_ONLY)."""

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
from crypto_trader.learning.growth_knowledge import (
    LESSON_CANDIDATE,
    LESSON_VALIDATED,
    PATTERN_CANDIDATE,
    PATTERN_CONTESTED,
    PATTERN_VALIDATED,
    EpisodeBinding,
    GrowthKnowledgePublisher,
    contains_absolute_rule,
    lesson_logical_id,
)
from crypto_trader.learning.growth_models import (
    GrowthLessonORM,
    GrowthPatternORM,
    create_growth_schema,
)
from crypto_trader.learning.growth_review import STATUS_SUCCEEDED, ReviewAttempt
from crypto_trader.persistence.models import AICoinProfileORM

SYMBOL = "BTCUSDT"
REGIME = "TREND"
DIRECTION = "LONG"
KNOWN_AT = datetime(2026, 9, 9, 12, tzinfo=UTC)


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
    statement: str = "Rising volume at entry is associated with trend continuation.",
    contrary_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> ReviewAttempt:
    refs = evidence_refs or [f"episode:{episode_id}", f"fill:{episode_id}_fill"]
    lesson = LessonSpec(
        statement=statement,
        testable_prediction="Future comparable episodes show the same association.",
        scope={"scope": "SYMBOL_REGIME", "symbols": [SYMBOL], "regimes": [REGIME]},
        evidence_refs=refs,
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
        review_date="2026-09-09",
        input_hash=f"input_{episode_id}",
    )


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


@pytest.fixture
def publisher(growth_db):
    return GrowthKnowledgePublisher(growth_db.session_factory, min_pattern_samples=3)


async def _latest_lesson(growth_db, lesson_id: str) -> GrowthLessonORM:
    async with growth_db.session_factory() as session:
        return (
            await session.execute(
                select(GrowthLessonORM)
                .where(GrowthLessonORM.lesson_id == lesson_id)
                .order_by(GrowthLessonORM.version.desc())
                .limit(1)
            )
        ).scalar_one()


async def _pattern_versions(growth_db, pattern_id: str) -> list[GrowthPatternORM]:
    async with growth_db.session_factory() as session:
        return list(
            (
                await session.execute(
                    select(GrowthPatternORM)
                    .where(GrowthPatternORM.pattern_id == pattern_id)
                    .order_by(GrowthPatternORM.version.asc())
                )
            )
            .scalars()
            .all()
        )


async def test_single_case_lesson_stays_candidate_with_explicit_axes(publisher, growth_db):
    report = await publisher.publish_review(
        attempt=_attempt("episode_1"), binding=_binding(), known_at=KNOWN_AT
    )
    assert report.lessons == 1
    lesson = await _latest_lesson(growth_db, _lesson_id_for("episode_1"))
    assert lesson.status == LESSON_CANDIDATE
    assert lesson.sample_count == 1
    assert lesson.independent_sample_count == 1
    assert lesson.hypothesis_support == "TESTABLE"
    assert lesson.data_completeness == "COMPLETE"
    assert lesson.measurement_quality == "FILL_DERIVED"
    # One case is not a published pattern; the candidate row stays audit-only.
    published = await publisher.list_published_patterns(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert published == []


def _lesson_id_for(episode_id: str) -> str:
    return lesson_logical_id(
        episode_id, "Rising volume at entry is associated with trend continuation."
    )


async def test_pattern_requires_independent_samples_and_dedupes(publisher, growth_db):
    for index in range(2):
        await publisher.publish_review(
            attempt=_attempt(f"episode_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert len(patterns) == 1
    candidate = patterns[0]
    assert candidate.status == PATTERN_CANDIDATE
    assert candidate.sample_count == 2
    assert candidate.support_grade == "INSUFFICIENT"

    third = await publisher.publish_review(
        attempt=_attempt("episode_2"), binding=_binding(), known_at=KNOWN_AT
    )
    assert third.pattern_status == PATTERN_VALIDATED
    version_after_third = third.pattern_version
    # Republishing exactly the same third episode must not inflate the sample.
    replay = await publisher.publish_review(
        attempt=_attempt("episode_2"), binding=_binding(), known_at=KNOWN_AT
    )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert pattern.sample_count == 3
    assert pattern.independent_sample_count == 3
    assert pattern.version == version_after_third
    assert replay.pattern_version == version_after_third


async def test_profitability_is_never_the_pattern_basis(publisher, growth_db):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"winning_episode_{index}"),
            binding=_binding(),
            known_at=KNOWN_AT,
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert pattern.status == PATTERN_VALIDATED
    assert pattern.features_json["profitability_used"] is False
    assert pattern.features_json["basis"] == "STRUCTURED_REVIEW_EVIDENCE_REFS"
    # The publisher never receives or stores a PnL/win-rate on the pattern.
    assert not hasattr(pattern, "win_rate")
    assert not hasattr(pattern, "net_pnl")


async def test_contrary_episode_downgrades_and_keeps_old_version(publisher, growth_db):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"support_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert pattern.status == PATTERN_VALIDATED
    pattern_id = pattern.pattern_id
    v1_id = pattern.id

    # R08: a contrary observation of the SAME proposition downgrades it.
    # A different proposition would not co-validate or downgrade this one.
    downgraded = await publisher.publish_review(
        attempt=_attempt(
            "contrary_1",
            statement="Rising volume at entry is associated with trend continuation.",
            contrary_refs=["tool:market_regime:candle:9"],
        ),
        binding=_binding(),
        known_at=KNOWN_AT,
    )
    assert downgraded.pattern_status == PATTERN_CONTESTED
    versions = await _pattern_versions(growth_db, pattern_id)
    # Each evidence change is a new retained version: 1..3 are the candidate
    # -> candidate -> validated progression, version 4 carries the contrary.
    assert [row.version for row in versions] == [1, 2, 3, 4]
    # v1_id was the validated version (3) captured before the contrary arrived.
    assert versions[2].id == v1_id
    assert versions[0].sample_count == 1
    assert versions[2].status == PATTERN_VALIDATED
    latest = versions[-1]
    assert latest.status == PATTERN_CONTESTED
    assert latest.contrary_count == 1
    assert latest.support_grade == "CONTESTED"
    assert latest.status_reason == "CONTRARY_EPISODES_PRESENT"


async def test_revoked_and_expired_and_future_knowledge_is_not_default_retrieved(
    publisher, growth_db
):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"support_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert await publisher.list_published_patterns(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME, as_of=KNOWN_AT
    )

    validated_versions = await _pattern_versions(growth_db, pattern.pattern_id)
    validated_id = validated_versions[-1].id
    await publisher.revoke(kind="pattern", logical_id=pattern.pattern_id, reason="MANUAL_REVIEW")
    # R07: the revocation version is visible at the transition time, while
    # historical as_of before it still sees the old validated version.
    assert (
        await publisher.list_published_patterns(
            account_id="default",
            mode="PAPER",
            symbol=SYMBOL,
            regime=REGIME,
            as_of=datetime.now(UTC),
        )
        == []
    )
    historical = await publisher.list_published_patterns(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME, as_of=KNOWN_AT
    )
    assert historical
    # Old versions are retained for audit; the current version is REVOKED.
    versions = await _pattern_versions(growth_db, pattern.pattern_id)
    assert versions[-1].status == "REVOKED"
    assert versions[-2].id == validated_id 

    # Future-known knowledge is invisible at the decision as-of time.
    future = KNOWN_AT + timedelta(days=2)
    await publisher.revoke(
        kind="pattern", logical_id=pattern.pattern_id, reason="RESET_FOR_FUTURE_TEST"
    )
    fresh = GrowthKnowledgePublisher(growth_db.session_factory, min_pattern_samples=3)
    for index in range(3):
        await fresh.publish_review(
            attempt=_attempt(f"future_{index}"), binding=_binding(), known_at=future
        )
    # R06/R07: at KNOWN_AT the latest *visible* version is the historical
    # validated version; the future rows must never leak backward.
    historical_again = await fresh.list_published_patterns(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME, as_of=KNOWN_AT
    )
    assert historical_again
    for row in historical_again:
        known = row.known_at
        if known is not None and known.tzinfo is None:
            known = known.replace(tzinfo=UTC)
        assert known is None or known <= KNOWN_AT


async def test_compression_requires_published_knowledge_and_is_conditional(
    publisher, growth_db
):
    for index in range(2):
        await publisher.publish_review(
            attempt=_attempt(f"case_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    assert (
        await publisher.compress(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
        is None
    )

    for index in range(2, 3):
        await publisher.publish_review(
            attempt=_attempt(f"case_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    compression = await publisher.compress(
        account_id="default",
        mode="PAPER",
        symbol=SYMBOL,
        regime=REGIME,
        known_at=KNOWN_AT,
    )
    assert compression is not None
    assert compression.status == "PUBLISHED"
    assert compression.sample_count == 3
    assert compression.source_knowledge_json[0]["kind"] == "PATTERN"
    assert compression.source_knowledge_json[0]["version"] == 3
    assert compression.invalidation_conditions_json
    assert compression.known_at == KNOWN_AT
    assert "conditional hypothesis" in compression.content
    assert "not a trading rule" in compression.content
    # A second compress with the same source set is the same row/version.
    again = await publisher.compress(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME, known_at=KNOWN_AT
    )
    assert again.id == compression.id and again.version == 1


async def test_compression_refuses_absolute_rule_language(publisher, growth_db):
    assert contains_absolute_rule("always enter after volume")
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"normal_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    pattern_row = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    proposition_key = (pattern_row.scope_json or {}).get("proposition_key", "legacy")
    # Simulate an eligible source lesson that smuggled in absolute language
    # (publication normally rejects it at lesson level).
    async with growth_db.session_factory() as session:
        session.add(
            GrowthLessonORM(
                lesson_id="lesson_smuggled",
                version=1,
                source_kind="EPISODE",
                source_id=(pattern_row.success_refs_json or ["support_0"])[0],
                episode_id=(pattern_row.success_refs_json or ["support_0"])[0],
                account_id="default",
                mode="PAPER",
                symbol=SYMBOL,
                direction=DIRECTION,
                regime=REGIME,
                statement="Always enter after volume.",
                observation_refs_json=[
                    f"episode:{(pattern_row.success_refs_json or ['support_0'])[0]}"
                ],
                support_refs_json=[
                    f"episode:{(pattern_row.success_refs_json or ['support_0'])[0]}"
                ],
                contrary_refs_json=[],
                scope_json={
                    "scope": "SYMBOL_REGIME",
                    "proposition_key": proposition_key,
                },
                status=LESSON_VALIDATED,
                sample_count=1,
                known_at=KNOWN_AT,
            )
        )
        await session.commit()
    with pytest.raises(ValueError, match="ABSOLUTE_RULE_LANGUAGE"):
        await publisher.compress(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )


async def test_coin_profile_uses_distinct_episodes_and_is_not_a_win_rate(
    publisher, growth_db
):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"support_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    async with growth_db.session_factory() as session:
        profile = (
            await session.execute(
                select(AICoinProfileORM).where(AICoinProfileORM.symbol == SYMBOL)
            )
        ).scalar_one()
    assert profile.sample_count == 3
    assert "NOT_A_WIN_RATE" in profile.behavior_tags_json
    assert "not profitability" in profile.profile_summary
    # No numeric win-rate/expectancy is derived from the episode count.
    assert not any(":" in str(item) and "WIN" in str(item) for item in profile.behavior_tags_json)


async def test_g03_pipeline_can_publish_g04_knowledge_idempotently(growth_db):
    from decimal import Decimal as _Decimal

    from crypto_trader.governance.daily_review import DailyReviewStats
    from crypto_trader.learning.growth_pipeline import (
        STAGE_SUCCEEDED,
        GrowthLearningPipeline,
        StageOutcome,
    )

    publisher = GrowthKnowledgePublisher(growth_db.session_factory, min_pattern_samples=3)
    pipeline = GrowthLearningPipeline(growth_db.session_factory, owner="worker-a")
    attempts = [_attempt(f"pipeline_case_{index}") for index in range(3)]
    bindings = {attempt.review.episode_id: _binding() for attempt in attempts}

    async def stats_runner() -> StageOutcome:
        return StageOutcome(
            STAGE_SUCCEEDED,
            payload={
                "net_status": "COMPLETE",
                "episode_count": 3,
                "daily_stats": DailyReviewStats(
                    date="2026-09-09", daily_pnl=_Decimal("1"), net_pnl=_Decimal("1")
                ),
            },
        )

    async def loader():
        return attempts

    async def review_runner(item):
        return item

    first = await pipeline.run_day(
        review_date="2026-09-09",
        account_id="default",
        mode="PAPER",
        source_revision="src-df55b11",
        profile_version="profile-v1",
        input_hash="pipeline_hash_v1",
        stats_runner=stats_runner,
        review_inputs_loader=loader,
        review_runner=review_runner,
        publisher=publisher.as_pipeline_publisher(bindings),
    )
    assert first.succeeded
    assert first.publish_status == STAGE_SUCCEEDED
    assert first.published_count >= 1
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert pattern.status == PATTERN_VALIDATED
    assert pattern.sample_count == 3

    replay = await pipeline.run_day(
        review_date="2026-09-09",
        account_id="default",
        mode="PAPER",
        source_revision="src-df55b11",
        profile_version="profile-v1",
        input_hash="pipeline_hash_v1",
        stats_runner=stats_runner,
        review_inputs_loader=loader,
        review_runner=review_runner,
        publisher=publisher.as_pipeline_publisher(bindings),
    )
    assert replay.idempotent is True
    pattern_after = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert pattern_after.version == pattern.version
    assert pattern_after.sample_count == 3
