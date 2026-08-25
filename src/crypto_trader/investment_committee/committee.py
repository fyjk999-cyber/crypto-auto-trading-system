"""Investment committee simulation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommitteeDecision:
    decision: str  # APPROVE | REJECT | WAIT | REDUCE_SIZE
    reason: str


class InvestmentCommittee:
    def decide(
        self, *, research_presentation: str, risk_review: str, quant_view: str, critic_view: str
    ) -> CommitteeDecision:
        if risk_review == "REJECT":
            return CommitteeDecision("REJECT", "risk_reject")
        if critic_view == "STRONG_AGAINST":
            return CommitteeDecision("WAIT", "critic_objection")
        if research_presentation == "OPPORTUNITY" and quant_view == "LONG":
            return CommitteeDecision("APPROVE", "committee_pass")
        return CommitteeDecision("REDUCE_SIZE", "committee_reduce")
