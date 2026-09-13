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
