from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.governance.reviewers import (
    AdversarialReviewer,
    HumanApprovalGate,
    ReviewDecision,
    RiskReviewer,
    StructuredReview,
)
from crypto_trader.governance.risk_levels import RiskLevel, RiskLevelInput, TradeRiskClassifier


@dataclass
class TradeReviewResult:
    level: RiskLevel
    decision: ReviewDecision
    reviews: list[StructuredReview] = field(default_factory=list)
    approved_position: Decimal = Decimal("0")
    approved_leverage: Decimal = Decimal("0")
    required_actions: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    human_approval_id: str | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class TradeReviewService:
    def __init__(self) -> None:
        self.classifier = TradeRiskClassifier()
        self.risk_reviewer = RiskReviewer()
        self.adversarial_reviewer = AdversarialReviewer()
        self.human_gate = HumanApprovalGate()

    def review(
        self,
        *,
        decision_id: str,
        risk_input: RiskLevelInput,
        risk_kwargs: dict,
        adversarial_kwargs: dict,
        proposed_position: Decimal,
        proposed_leverage: Decimal,
        human_approved: bool | None = None,
        now: datetime | None = None,
    ) -> TradeReviewResult:
        level = self.classifier.classify(risk_input)
        reviews: list[StructuredReview] = []
        if level == RiskLevel.L1:
            reviews.append(
                StructuredReview(
                    decision=ReviewDecision.PASS,
                    risk_score=D("0"),
                    reviewer="automatic",
                    reason_codes=["L1_AUTOMATIC"],
                )
            )
            return TradeReviewResult(
                level=level,
                decision=ReviewDecision.PASS,
                reviews=reviews,
                approved_position=proposed_position,
                approved_leverage=proposed_leverage,
                reason_codes=["L1_AUTOMATIC"],
            )
        risk_review = self.risk_reviewer.review(**risk_kwargs)
        reviews.append(risk_review)
        if level == RiskLevel.L2:
            if risk_review.decision in (ReviewDecision.PASS, ReviewDecision.REDUCE):
                decision = (
                    ReviewDecision.PASS
                    if risk_review.decision == ReviewDecision.PASS
                    else ReviewDecision.REDUCE
                )
                pos = (
                    proposed_position
                    if decision == ReviewDecision.PASS
                    else proposed_position * D("0.8")
                )
                lev = (
                    proposed_leverage
                    if decision == ReviewDecision.PASS
                    else min(proposed_leverage, D("3"))
                )
                return TradeReviewResult(
                    level=level,
                    decision=decision,
                    reviews=reviews,
                    approved_position=pos,
                    approved_leverage=lev,
                    required_actions=risk_review.required_actions,
                    reason_codes=risk_review.reason_codes,
                )
            return TradeReviewResult(
                level=level,
                decision=risk_review.decision,
                reviews=reviews,
                approved_position=D("0"),
                approved_leverage=D("0"),
                reason_codes=risk_review.reason_codes,
            )

        # L3/L4: adversarial + risk
        adv_review = self.adversarial_reviewer.review(**adversarial_kwargs)
        reviews.append(adv_review)
        decisions = [r.decision for r in reviews]
        if ReviewDecision.REJECT in decisions:
            final = ReviewDecision.REJECT
        elif level == RiskLevel.L4:
            if human_approved is None:
                self.human_gate.request(decision_id, now=now)
                return TradeReviewResult(
                    level=level,
                    decision=ReviewDecision.WAITING_APPROVAL,
                    reviews=reviews,
                    approved_position=D("0"),
                    approved_leverage=D("0"),
                    human_approval_id=decision_id,
                    reason_codes=["L4_HUMAN_APPROVAL_REQUIRED"],
                )
            final = self.human_gate.resolve(decision_id, human_approved, now=now)
        elif ReviewDecision.ESCALATE in decisions:
            final = ReviewDecision.ESCALATE
        elif ReviewDecision.REDUCE in decisions:
            final = ReviewDecision.REDUCE
        else:
            final = ReviewDecision.PASS
        if final in (ReviewDecision.PASS, ReviewDecision.REDUCE):
            pos = (
                proposed_position if final == ReviewDecision.PASS else proposed_position * D("0.6")
            )
            lev = (
                proposed_leverage
                if final == ReviewDecision.PASS
                else min(proposed_leverage, D("2"))
            )
        else:
            pos, lev = D("0"), D("0")
        return TradeReviewResult(
            level=level,
            decision=final,
            reviews=reviews,
            approved_position=pos,
            approved_leverage=lev,
            required_actions=[a for r in reviews for a in r.required_actions],
            reason_codes=[c for r in reviews for c in r.reason_codes],
        )
