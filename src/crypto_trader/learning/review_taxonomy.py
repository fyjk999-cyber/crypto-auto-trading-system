"""Growth V2 lifecycle review taxonomy (Phase 5).

SPEC requires seven distinct reviews over the full lifecycle:

    ADD / HEDGE / EXIT_MODIFICATION / FAST_PROFIT / REENTRY / RISK /
    LLM_INVOCATION

Each review carries a verdict and a lesson, and is learning/observability only —
Growth never trades and never modifies Risk hard rules, execution safety, model
formulas or order authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ReviewType(StrEnum):
    ADD_REVIEW = "ADD_REVIEW"
    HEDGE_REVIEW = "HEDGE_REVIEW"
    EXIT_MODIFICATION_REVIEW = "EXIT_MODIFICATION_REVIEW"
    FAST_PROFIT_REVIEW = "FAST_PROFIT_REVIEW"
    REENTRY_REVIEW = "REENTRY_REVIEW"
    RISK_REVIEW = "RISK_REVIEW"
    LLM_INVOCATION_REVIEW = "LLM_INVOCATION_REVIEW"


REQUIRED_REVIEW_TYPES: tuple[str, ...] = tuple(item.value for item in ReviewType)

REVIEW_VERDICTS = ("CORRECT", "SUBOPTIMAL", "DEFECT", "INCONCLUSIVE")

_EVENT_MAP = {
    "ADD": ReviewType.ADD_REVIEW,
    "HEDGE": ReviewType.HEDGE_REVIEW,
    "REVERSE": ReviewType.HEDGE_REVIEW,
    "MODIFY_EXIT": ReviewType.EXIT_MODIFICATION_REVIEW,
    "EXIT_MODIFICATION": ReviewType.EXIT_MODIFICATION_REVIEW,
    "BASE_EXIT": ReviewType.EXIT_MODIFICATION_REVIEW,
    "FAST_PROFIT": ReviewType.FAST_PROFIT_REVIEW,
    "FAST_PROFIT_PROTECTION": ReviewType.FAST_PROFIT_REVIEW,
    "RE_ENTRY": ReviewType.REENTRY_REVIEW,
    "REENTRY": ReviewType.REENTRY_REVIEW,
    "RISK_L1": ReviewType.RISK_REVIEW,
    "RISK_L2": ReviewType.RISK_REVIEW,
    "RISK_HARD_EXIT": ReviewType.RISK_REVIEW,
    "LLM_INVOCATION": ReviewType.LLM_INVOCATION_REVIEW,
    "LLM_REASSESSMENT": ReviewType.LLM_INVOCATION_REVIEW,
}


@dataclass
class ReviewFinding:
    review_type: str
    verdict: str
    event_kind: str
    observations: list[str] = field(default_factory=list)
    lesson: str = ""
    authority: str = "LEARNING_ONLY"
    is_order: bool = False


def review_type_for(event_kind: str) -> str | None:
    return _EVENT_MAP.get((event_kind or "").upper())


def classify_review(
    *,
    event_kind: str,
    outcome_bps: float | None = None,
    notes: str = "",
) -> ReviewFinding | None:
    """Map one lifecycle event to its required review with a factual verdict."""
    review_type = review_type_for(event_kind)
    if review_type is None:
        return None
    if outcome_bps is None:
        verdict = "INCONCLUSIVE"
    elif outcome_bps > 0:
        verdict = "CORRECT"
    elif outcome_bps < 0:
        verdict = "DEFECT"
    else:
        verdict = "SUBOPTIMAL"
    observations = [f"outcome_bps={outcome_bps}"] if outcome_bps is not None else []
    if notes:
        observations.append(notes)
    lesson = (
        f"{review_type.value}: {verdict.lower()} with outcome_bps={outcome_bps}"
        if outcome_bps is not None
        else f"{review_type.value}: awaiting factual outcome"
    )
    return ReviewFinding(
        review_type=review_type.value,
        verdict=verdict,
        event_kind=event_kind.upper(),
        observations=observations,
        lesson=lesson,
    )


def review_coverage(events: list[dict]) -> dict:
    """Count how many of the seven required reviews the supplied events cover."""
    counts = {review_type: 0 for review_type in REQUIRED_REVIEW_TYPES}
    for event in events:
        review = classify_review(
            event_kind=str(event.get("kind") or event.get("lifecycle_action") or ""),
            outcome_bps=event.get("outcome_bps"),
            notes=str(event.get("notes") or ""),
        )
        if review is not None:
            counts[review.review_type] += 1
    covered = [review_type for review_type, count in counts.items() if count > 0]
    return {
        "counts": counts,
        "covered": covered,
        "missing": [item for item in REQUIRED_REVIEW_TYPES if item not in covered],
        "complete": len(covered) == len(REQUIRED_REVIEW_TYPES),
        "authority": "LEARNING_ONLY",
        "not_an_order": True,
    }
