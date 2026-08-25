"""AI strategy optimization: proposals only, never direct mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class OptimizationProposal:
    proposal_id: str
    title: str
    parameter_changes: dict
    status: str = "PROPOSED"
    evidence: list[str] = None
    created_at: str = ""


class AIOptimizer:
    def propose(self, proposal_id: str, pattern: str) -> OptimizationProposal:
        if pattern == "TREND_WORKS_HIGH_VOL":
            return OptimizationProposal(
                proposal_id=proposal_id,
                title="Increase trend weight in high volatility",
                parameter_changes={"trend_weight_high_vol": "0.50"},
                evidence=[],
                created_at=datetime.now(UTC).isoformat(),
            )
        return OptimizationProposal(
            proposal_id=proposal_id,
            title="No optimization",
            parameter_changes={},
            evidence=[],
            created_at=datetime.now(UTC).isoformat(),
        )

    def validate(self, proposal: OptimizationProposal, evidence: list[str]) -> bool:
        required = {"BACKTEST_PASS", "WALK_FORWARD_PASS", "SHADOW_PASS"}
        return required.issubset(set(evidence)) and bool(proposal.parameter_changes)

    def promote(self, proposal: OptimizationProposal, evidence: list[str]) -> bool:
        if not self.validate(proposal, evidence):
            return False
        proposal.status = "PROMOTED"
        return True

    def rollback(self, proposal: OptimizationProposal) -> bool:
        if proposal.status != "PROMOTED":
            return False
        proposal.status = "ROLLED_BACK"
        return True
