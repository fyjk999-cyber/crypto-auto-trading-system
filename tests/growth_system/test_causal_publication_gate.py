"""A.5.2 accounting subtype + episode-ref causal gate tests."""
import pytest

from crypto_trader.learning.growth_review_evidence import (
    CausalEvidenceUnavailable,
    GrowthReviewEvidence,
    validate_causal_evidence_refs,
)


def test_accounting_subtypes_are_independent():
    fees_only = GrowthReviewEvidence(
        episode_id="ep", fees_availability="AVAILABLE",
        funding_availability="UNAVAILABLE",
    )
    validate_causal_evidence_refs(fees_only, ["accounting:fees"])
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(fees_only, ["accounting:funding"])
    funding_only = GrowthReviewEvidence(
        episode_id="ep", fees_availability="UNAVAILABLE",
        funding_availability="AVAILABLE",
    )
    validate_causal_evidence_refs(funding_only, ["accounting:funding"])
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(funding_only, ["accounting:fees"])


def test_unknown_accounting_subtype_rejected():
    ev = GrowthReviewEvidence(episode_id="ep")
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(ev, ["accounting:profit"])


def test_episode_ref_must_match_identity():
    ev = GrowthReviewEvidence(episode_id="ep")
    validate_causal_evidence_refs(ev, ["episode:ep"])
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(ev, ["episode:other"])


def test_pub_mixed_refs_are_blocked_atomically_by_validator():
    ev = GrowthReviewEvidence(
        episode_id="ep-pub-mixed",
        fees_availability="AVAILABLE",
        funding_availability="UNAVAILABLE",
    )
    # The valid episode ref alone passes...
    validate_causal_evidence_refs(ev, ["episode:ep-pub-mixed"])
    # ...but a claim containing an unavailable funding ref must be rejected as
    # a whole; callers must not strip the bad ref and publish the rest.
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(
            ev, ["episode:ep-pub-mixed", "accounting:funding"]
        )


def _attempt(lessons, *, episode_id, attempt_id="attempt-cp1", metadata=None):
    from crypto_trader.learning.growth_contracts import (
        ObservationFact,
        StructuredReview,
        TestableLesson,
    )
    from crypto_trader.learning.growth_review import STATUS_SUCCEEDED, ReviewAttempt

    review = StructuredReview(
        episode_id=episode_id,
        observation_facts=[ObservationFact(statement="f", evidence_refs=[f"episode:{episode_id}"])],
        testable_lessons=[
            TestableLesson(
                statement=statement,
                testable_prediction="prediction",
                scope={"scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"], "regimes": ["TRENDING"]},
                evidence_refs=refs,
            )
            for statement, refs in lessons
        ],
    )
    values = dict(
        status=STATUS_SUCCEEDED, attempt_id=attempt_id, review=review,
        account_id="default", mode="PAPER", symbol="BTCUSDT",
        direction="LONG", review_date="2026-09-09", input_hash="hash-cp1",
    )
    values.update(metadata or {})
    return ReviewAttempt(**values)


def test_pub02_single_unavailable_ref_blocks_whole_claim():
    from crypto_trader.learning.growth_runtime_learning import _prepare_publication_attempt

    evidence = GrowthReviewEvidence(
        episode_id="ep-pub02", fees_availability="AVAILABLE",
        funding_availability="UNAVAILABLE",
    )
    raw = _attempt(
        [("PUB02_BLOCKED", ["episode:ep-pub02", "accounting:funding"])],
        episode_id="ep-pub02",
    )
    safe, blocked = _prepare_publication_attempt(raw, evidence=evidence)
    assert safe is None
    assert raw.review.testable_lessons[0].statement == "PUB02_BLOCKED"
    assert any("EVIDENCE_UNAVAILABLE:accounting:funding" in item for item in blocked)


def test_pub03_mixed_copy_keeps_two_safe_lessons_without_mutating_raw():
    from crypto_trader.learning.growth_runtime_learning import _prepare_publication_attempt

    evidence = GrowthReviewEvidence(
        episode_id="ep-pub03", fees_availability="AVAILABLE",
        funding_availability="UNAVAILABLE",
    )
    raw = _attempt(
        [
            ("PUB03_SAFE_EPISODE", ["episode:ep-pub03"]),
            ("PUB03_BLOCKED_FUNDING", ["accounting:funding"]),
            ("PUB03_SAFE_FEES", ["accounting:fees"]),
        ],
        episode_id="ep-pub03",
    )
    before = raw.review.model_dump(mode="json")
    safe, blocked = _prepare_publication_attempt(raw, evidence=evidence)
    assert safe is not None and safe is not raw and safe.review is not raw.review
    assert [x.statement for x in safe.review.testable_lessons] == [
        "PUB03_SAFE_EPISODE", "PUB03_SAFE_FEES",
    ]
    assert [x.statement for x in raw.review.testable_lessons] == [
        "PUB03_SAFE_EPISODE", "PUB03_BLOCKED_FUNDING", "PUB03_SAFE_FEES",
    ]
    assert raw.review.model_dump(mode="json") == before
    assert safe.attempt_id == raw.attempt_id and safe.input_hash == raw.input_hash
    assert any("EVIDENCE_UNAVAILABLE:accounting:funding" in item for item in blocked)


@pytest.fixture
async def growth_db(database):
    from crypto_trader.learning.growth_models import create_growth_schema
    await create_growth_schema(database.engine)
    return database


async def test_cp2a_valid_claim_reaches_reusable_knowledge(growth_db):
    from sqlalchemy import select

    from crypto_trader.learning.growth_knowledge import proposition_identity
    from crypto_trader.learning.growth_models import (
        GrowthLessonORM,
        GrowthPatternORM,
        GrowthReviewAttemptORM,
    )
    from crypto_trader.learning.growth_runtime_learning import (
        GrowthRuntimeLearningService,
    )
    from tests.growth_system.test_review_schema_and_refs import FakeProvider
    from tests.growth_system.test_runtime_learning_closure import (
        _episode,
        _payload,
        _seed_episode,
        _true,
    )

    episode = _episode("ep-pub01")
    await _seed_episode(growth_db, episode)
    scope = {
        "scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"],
        "regimes": ["TRENDING"],
    }
    lesson = {
        "statement": "PUB01_VALID_LESSON",
        "testable_prediction": "PUB01 prediction",
        "scope": scope,
        "evidence_refs": ["episode:ep-pub01"],
        "contrary_refs": [],
        "uncertainty": "candidate",
        "confidence": "LOW",
    }
    service = GrowthRuntimeLearningService(
        growth_db.session_factory,
        provider=FakeProvider([_payload("ep-pub01", lessons=[lesson])]),
        min_pattern_samples=3,
    )
    report = await service.run(
        [episode], review_date="2026-09-09", claim_token="token-r4",
        owner="worker", fence=_true,
    )
    async with growth_db.session_factory() as session:
        attempt = (await session.execute(select(GrowthReviewAttemptORM).where(
            GrowthReviewAttemptORM.episode_id == "ep-pub01"))).scalar_one()
        lessons = (await session.execute(select(GrowthLessonORM).where(
            GrowthLessonORM.statement == "PUB01_VALID_LESSON"))).scalars().all()
        patterns = (await session.execute(select(GrowthPatternORM))).scalars().all()
    assert attempt.status == "SUCCEEDED"
    assert "PUB01_VALID_LESSON" in str(attempt.result_json)
    assert len(lessons) == 1
    assert lessons[0].support_refs_json == ["episode:ep-pub01"]
    assert lessons[0].contrary_refs_json == []
    key = proposition_identity("PUB01_VALID_LESSON", scope)
    assert any((row.scope_json or {}).get("proposition_key") == key for row in patterns)
    assert report.structured_reviews_created == 1
    assert report.reviews_with_causal_lessons == 1


async def test_cp2b_runtime_mixed_preserves_raw_and_filters_publisher(
    growth_db, monkeypatch
):
    from sqlalchemy import select

    import crypto_trader.learning.growth_runtime_learning as runtime_module
    from crypto_trader.learning.growth_knowledge import proposition_identity
    from crypto_trader.learning.growth_models import (
        GrowthLessonORM,
        GrowthPatternORM,
        GrowthReviewAttemptORM,
    )
    from crypto_trader.learning.growth_runtime_learning import (
        GrowthRuntimeLearningService,
    )
    from crypto_trader.persistence.models import AITradeReviewORM
    from tests.growth_system.test_review_schema_and_refs import FakeProvider
    from tests.growth_system.test_runtime_learning_closure import (
        _episode,
        _payload,
        _seed_episode,
        _true,
    )

    episode = _episode("ep-pub07")
    await _seed_episode(growth_db, episode)
    scope = {
        "scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"],
        "regimes": ["TRENDING"],
    }
    safe = {
        "statement": "PUB07_SAFE", "testable_prediction": "safe prediction",
        "scope": scope, "evidence_refs": ["episode:ep-pub07"],
        "contrary_refs": [], "uncertainty": "candidate", "confidence": "LOW",
    }
    blocked = {
        "statement": "PUB07_BLOCKED", "testable_prediction": "blocked prediction",
        "scope": scope, "evidence_refs": ["accounting:fees"],
        "contrary_refs": [], "uncertainty": "candidate", "confidence": "LOW",
    }
    service = GrowthRuntimeLearningService(
        growth_db.session_factory,
        provider=FakeProvider([_payload("ep-pub07", lessons=[safe, blocked])]),
        min_pattern_samples=3,
    )
    events, captured = [], {}
    real_validator = runtime_module.validate_causal_evidence_refs

    def validator_spy(evidence, refs):
        refs = list(refs)
        events.append(("validate", tuple(refs)))
        real_validator(evidence, refs)
        if evidence.episode_id == "ep-pub07" and "accounting:fees" in refs:
            raise CausalEvidenceUnavailable("EVIDENCE_UNAVAILABLE:accounting:fees")

    monkeypatch.setattr(runtime_module, "validate_causal_evidence_refs", validator_spy)
    real_review = service.review_service.review

    async def review_spy(*args, **kwargs):
        attempt = await real_review(*args, **kwargs)
        captured["raw_attempt"] = attempt
        return attempt

    monkeypatch.setattr(service.review_service, "review", review_spy)
    real_publish = service.publisher.publish_attempts

    async def publish_spy(attempts, **kwargs):
        attempts = list(attempts)
        events.append(("publisher", None))
        captured["publisher_attempts"] = attempts
        return await real_publish(attempts, **kwargs)

    monkeypatch.setattr(service.publisher, "publish_attempts", publish_spy)
    report = await service.run(
        [episode], review_date="2026-09-09", claim_token="token-r4",
        owner="worker", fence=_true,
    )
    validates = [i for i, e in enumerate(events) if e[0] == "validate"]
    publishers = [i for i, e in enumerate(events) if e[0] == "publisher"]
    assert len(validates) >= 2 and len(publishers) == 1
    assert max(validates) < publishers[0]
    raw_attempt = captured["raw_attempt"]
    publisher_attempt = captured["publisher_attempts"][0]
    assert publisher_attempt is not raw_attempt
    assert publisher_attempt.review is not raw_attempt.review
    assert publisher_attempt.attempt_id == raw_attempt.attempt_id
    assert publisher_attempt.input_hash == raw_attempt.input_hash
    assert [x.statement for x in publisher_attempt.review.testable_lessons] == ["PUB07_SAFE"]
    assert [
        item.statement for item in raw_attempt.review.testable_lessons
    ] == ["PUB07_SAFE", "PUB07_BLOCKED"]
    async with growth_db.session_factory() as session:
        row = (await session.execute(select(GrowthReviewAttemptORM).where(
            GrowthReviewAttemptORM.episode_id == "ep-pub07"))).scalar_one()
        audit = (await session.execute(select(AITradeReviewORM).where(
            AITradeReviewORM.episode_id == "ep-pub07"))).scalar_one()
        safe_rows = (await session.execute(select(GrowthLessonORM).where(
            GrowthLessonORM.statement == "PUB07_SAFE"))).scalars().all()
        blocked_rows = (await session.execute(select(GrowthLessonORM).where(
            GrowthLessonORM.statement == "PUB07_BLOCKED"))).scalars().all()
        patterns = (await session.execute(select(GrowthPatternORM))).scalars().all()
    assert row.status == "SUCCEEDED"
    raw_statements = [i["statement"] for i in row.result_json["testable_lessons"]]
    assert "PUB07_SAFE" in raw_statements and "PUB07_BLOCKED" in raw_statements
    assert "PUB07_SAFE" in (audit.lessons_json or [])
    assert "PUB07_BLOCKED" in (audit.lessons_json or [])
    assert safe_rows and not blocked_rows
    assert safe_rows[-1].support_refs_json == ["episode:ep-pub07"]
    blocked_key = proposition_identity("PUB07_BLOCKED", scope)
    assert all((r.scope_json or {}).get("proposition_key") != blocked_key for r in patterns)
    assert report.structured_reviews_created == 1
    assert report.reviews_with_causal_lessons == 1
    assert any("CAUSAL_EVIDENCE_BLOCKED" in e and "accounting:fees" in e for e in report.errors)


async def test_cp3a_zero_safe_stops_before_publisher_and_cards(
    growth_db, monkeypatch
):
    from sqlalchemy import select

    import crypto_trader.learning.growth_runtime_learning as runtime_module
    from crypto_trader.learning.growth_knowledge import proposition_identity
    from crypto_trader.learning.growth_models import (
        GrowthLessonORM,
        GrowthPatternORM,
        GrowthReviewAttemptORM,
    )
    from crypto_trader.learning.growth_runtime_learning import (
        GrowthRuntimeLearningService,
    )
    from tests.growth_system.test_review_schema_and_refs import FakeProvider
    from tests.growth_system.test_runtime_learning_closure import (
        _episode,
        _payload,
        _seed_episode,
        _true,
    )

    episode = _episode("ep-pub06b")
    await _seed_episode(growth_db, episode)
    scope = {"scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"], "regimes": ["TRENDING"]}
    lesson = {
        "statement": "PUB06B_BLOCKED", "testable_prediction": "p",
        "scope": scope, "evidence_refs": ["episode:ep-pub06b"],
        "contrary_refs": [], "uncertainty": "candidate", "confidence": "LOW",
    }
    service = GrowthRuntimeLearningService(
        growth_db.session_factory,
        provider=FakeProvider([_payload("ep-pub06b", lessons=[lesson])]),
        min_pattern_samples=3,
    )
    real_validator = runtime_module.validate_causal_evidence_refs

    def validator_spy(evidence, refs):
        refs = list(refs)
        real_validator(evidence, refs)
        if evidence.episode_id == "ep-pub06b" and "episode:ep-pub06b" in refs:
            raise CausalEvidenceUnavailable("EVIDENCE_UNAVAILABLE:episode:ep-pub06b")

    monkeypatch.setattr(runtime_module, "validate_causal_evidence_refs", validator_spy)
    publisher_calls = 0
    card_calls = 0

    async def publisher_trap(*args, **kwargs):
        nonlocal publisher_calls
        publisher_calls += 1
        pytest.fail("publisher must not be called")

    async def cards_trap(*args, **kwargs):
        nonlocal card_calls
        card_calls += 1
        pytest.fail("cards must not be materialized")

    monkeypatch.setattr(service.publisher, "publish_attempts", publisher_trap)
    monkeypatch.setattr(service, "_materialize_cards", cards_trap)
    report = await service.run(
        [episode], review_date="2026-09-09", claim_token="token-r4",
        owner="worker", fence=_true,
    )
    async with growth_db.session_factory() as session:
        attempt = (await session.execute(select(GrowthReviewAttemptORM).where(
            GrowthReviewAttemptORM.episode_id == "ep-pub06b"))).scalar_one()
        lessons = (await session.execute(select(GrowthLessonORM).where(
            GrowthLessonORM.statement == "PUB06B_BLOCKED"))).scalars().all()
        patterns = (await session.execute(select(GrowthPatternORM))).scalars().all()
    assert attempt.status == "SUCCEEDED"
    assert "PUB06B_BLOCKED" in str(attempt.result_json)
    assert publisher_calls == 0 and card_calls == 0
    assert lessons == []
    blocked_key = proposition_identity("PUB06B_BLOCKED", scope)
    assert all((r.scope_json or {}).get("proposition_key") != blocked_key for r in patterns)
    assert report.structured_reviews_created == 1
    assert report.reviews_with_causal_lessons == 0
    assert report.lessons_created == 0 and report.patterns_created == 0
    assert report.cards_created == 0 and report.status == "REVIEW_ONLY"
    assert any("CAUSAL_EVIDENCE_BLOCKED" in e for e in report.errors)


async def test_cp3b_future_rule_scope_not_contrary_refs(growth_db):
    from sqlalchemy import select

    from crypto_trader.learning.growth_models import (
        GrowthLessonORM,
        GrowthReviewAttemptORM,
    )
    from crypto_trader.learning.growth_runtime_learning import (
        GrowthRuntimeLearningService,
    )
    from crypto_trader.persistence.models import AITradeReviewORM
    from tests.growth_system.test_review_schema_and_refs import FakeProvider
    from tests.growth_system.test_runtime_learning_closure import (
        _episode,
        _payload,
        _seed_episode,
        _true,
    )

    episode = _episode("ep-future-rule")
    await _seed_episode(growth_db, episode)
    rule = {
        "statement": "PUB_FUTURE_VALID",
        "evidence_refs": ["episode:ep-future-rule"],
        "confidence": "LOW",
        "applicability": {"regime": "TRENDING", "direction": "LONG"},
        "counter_conditions": ["follow-through volume absent"],
    }
    service = GrowthRuntimeLearningService(
        growth_db.session_factory,
        provider=FakeProvider([_payload("ep-future-rule", lessons=[], future_rules=[rule])]),
        min_pattern_samples=3,
    )
    report = await service.run(
        [episode], review_date="2026-09-09", claim_token="token-r4",
        owner="worker", fence=_true,
    )
    async with growth_db.session_factory() as session:
        attempt = (await session.execute(select(GrowthReviewAttemptORM).where(
            GrowthReviewAttemptORM.episode_id == "ep-future-rule"))).scalar_one()
        audit = (await session.execute(select(AITradeReviewORM).where(
            AITradeReviewORM.episode_id == "ep-future-rule"))).scalar_one()
        lesson = (await session.execute(select(GrowthLessonORM).where(
            GrowthLessonORM.statement == "PUB_FUTURE_VALID"))).scalar_one()
    assert attempt.status == "SUCCEEDED"
    assert attempt.result_json["testable_lessons"] == []
    raw_rule = attempt.result_json["future_rules"][0]
    assert raw_rule["statement"] == "PUB_FUTURE_VALID"
    assert raw_rule["counter_conditions"] == ["follow-through volume absent"]
    assert audit.future_rules_json[0]["counter_conditions"] == ["follow-through volume absent"]
    assert lesson.support_refs_json == ["episode:ep-future-rule"]
    assert lesson.contrary_refs_json == []
    assert (lesson.scope_json or {})["counter_conditions"] == ["follow-through volume absent"]
    all_refs = list(lesson.support_refs_json or []) + list(lesson.contrary_refs_json or [])
    assert all_refs == ["episode:ep-future-rule"]
    assert report.structured_reviews_created == 1
    assert report.reviews_with_future_rules == 1
    assert report.reviews_with_causal_lessons == 1


def test_cp3b_unavailable_future_rule_is_not_published():
    from crypto_trader.learning.growth_contracts import (
        LearningItem,
        ObservationFact,
        StructuredReview,
    )
    from crypto_trader.learning.growth_review import (
        STATUS_SUCCEEDED,
        ReviewAttempt,
    )
    from crypto_trader.learning.growth_runtime_learning import (
        _prepare_publication_attempt,
    )

    evidence = GrowthReviewEvidence(
        episode_id="ep-future-blocked", funding_availability="UNAVAILABLE"
    )
    review = StructuredReview(
        episode_id="ep-future-blocked",
        observation_facts=[ObservationFact(
            statement="f", evidence_refs=["episode:ep-future-blocked"],
        )],
        testable_lessons=[],
        future_rules=[LearningItem(
            statement="PUB_FUTURE_BLOCKED",
            evidence_refs=["accounting:funding"],
            confidence="LOW",
            applicability={"regime": "TRENDING", "direction": "LONG"},
            counter_conditions=["funding regime normalizes"],
        )],
    )
    attempt = ReviewAttempt(
        status=STATUS_SUCCEEDED, attempt_id="attempt-future-blocked",
        review=review, account_id="default", mode="PAPER",
        symbol="BTCUSDT", direction="LONG",
        review_date="2026-09-09", input_hash="hash-future-blocked",
    )
    before = attempt.review.model_dump(mode="json")
    safe, blocked = _prepare_publication_attempt(attempt, evidence=evidence)
    assert safe is None
    assert attempt.review.model_dump(mode="json") == before
    assert attempt.review.future_rules[0].statement == "PUB_FUTURE_BLOCKED"
    assert any("EVIDENCE_UNAVAILABLE:accounting:funding" in item for item in blocked)


def test_absolute_trading_rule_is_blocked_before_publisher():
    from crypto_trader.learning.growth_runtime_learning import (
        _prepare_publication_attempt,
    )

    evidence = GrowthReviewEvidence(episode_id="ep-abs-rule")
    raw = _attempt(
        [("Always enter after volume.", ["episode:ep-abs-rule"])],
        episode_id="ep-abs-rule",
    )
    before = raw.review.model_dump(mode="json")
    safe, blocked = _prepare_publication_attempt(raw, evidence=evidence)
    assert safe is None
    assert raw.review.model_dump(mode="json") == before
    assert any(
        "ABSOLUTE_RULE_LANGUAGE_BLOCKED:ep-abs-rule" in item
        for item in blocked
    )
