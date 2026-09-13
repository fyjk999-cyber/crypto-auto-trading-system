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
