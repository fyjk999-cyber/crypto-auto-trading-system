"""DeepSeek large capital risk review -> deterministic adjustments."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.deepseek.schemas import CapitalReview


@dataclass
class CommitteeResult:
    decision: str
    approved_size: Decimal
    approved_leverage: Decimal
    reason: str


def apply_capital_review(
    requested_size: Decimal, requested_leverage: Decimal, review: CapitalReview | None
) -> CommitteeResult:
    if review is None:
        return CommitteeResult(
            "ADJUST",
            requested_size * Decimal("0.5"),
            min(requested_leverage, Decimal("2")),
            "NO_AI_REVIEW_FALLBACK",
        )
    if review.decision == "APPROVE":
        return CommitteeResult("APPROVE", requested_size, requested_leverage, review.reasoning)
    if review.decision == "REJECT":
        return CommitteeResult("REJECT", Decimal("0"), Decimal("0"), review.reasoning)
    return CommitteeResult(
        "ADJUST",
        Decimal(str(review.recommended_size)),
        Decimal(str(review.recommended_leverage)),
        review.reasoning,
    )
