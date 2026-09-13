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
