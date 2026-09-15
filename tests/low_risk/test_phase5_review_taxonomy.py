"""Phase 5: the seven required lifecycle reviews."""

from __future__ import annotations

from crypto_trader.learning.review_taxonomy import (
    REQUIRED_REVIEW_TYPES,
    classify_review,
    review_coverage,
    review_type_for,
)


def test_all_seven_review_types_are_mapped() -> None:
    mapping = {
        "ADD": "ADD_REVIEW",
        "HEDGE": "HEDGE_REVIEW",
        "REVERSE": "HEDGE_REVIEW",
        "MODIFY_EXIT": "EXIT_MODIFICATION_REVIEW",
        "FAST_PROFIT_PROTECTION": "FAST_PROFIT_REVIEW",
        "RE_ENTRY": "REENTRY_REVIEW",
        "RISK_L2": "RISK_REVIEW",
        "LLM_REASSESSMENT": "LLM_INVOCATION_REVIEW",
    }
    for kind, expected in mapping.items():
        assert review_type_for(kind) == expected
    assert review_type_for("SOMETHING_ELSE") is None
    assert len(REQUIRED_REVIEW_TYPES) == 7


def test_review_verdicts_follow_factual_outcome() -> None:
    good = classify_review(event_kind="ADD", outcome_bps=42.0)
    bad = classify_review(event_kind="FAST_PROFIT", outcome_bps=-7.5)
    pending = classify_review(event_kind="RISK_L1")
    assert good is not None and good.verdict == "CORRECT"
    assert good.review_type == "ADD_REVIEW"
    assert bad is not None and bad.verdict == "DEFECT"
    assert pending is not None and pending.verdict == "INCONCLUSIVE"
    assert good.authority == "LEARNING_ONLY"
    assert good.is_order is False


def test_review_coverage_tracks_missing_taxonomy() -> None:
    events = [
        {"kind": "ADD", "outcome_bps": 5.0},
        {"kind": "HEDGE", "outcome_bps": -2.0},
        {"kind": "MODIFY_EXIT"},
        {"kind": "FAST_PROFIT_PROTECTION", "outcome_bps": 10.0},
        {"kind": "REENTRY", "outcome_bps": -1.0},
        {"kind": "RISK_L2", "outcome_bps": 0.0},
        {"kind": "LLM_INVOCATION", "outcome_bps": 8.0},
        {"kind": "UNKNOWN_EVENT"},
    ]
    coverage = review_coverage(events)
    assert coverage["complete"] is True
    assert coverage["missing"] == []
    assert coverage["counts"]["HEDGE_REVIEW"] == 1
    assert coverage["counts"]["RISK_REVIEW"] == 1
    assert coverage["not_an_order"] is True

    partial = review_coverage(events[:2])
    assert partial["complete"] is False
    assert "RISK_REVIEW" in partial["missing"]
