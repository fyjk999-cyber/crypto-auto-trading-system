"""AI alpha discovery: proposals only, never direct production mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class StrategyProposal:
    proposal_id: str
    title: str
    rules: dict
    status: str = "PROPOSED"
    evidence: list[str] = None
    created_at: str = ""


class StrategyGenerator:
    def generate(self, proposal_id: str, pattern: str) -> StrategyProposal:
        if pattern == "BREAKOUT_OI_FUNDING":
            return StrategyProposal(
                proposal_id=proposal_id,
                title="BTC breakout with OI rising and funding neutral",
                rules={"indicator": "breakout", "oi_filter": "rising", "funding_filter": "neutral"},
                evidence=[],
                created_at=datetime.now(UTC).isoformat(),
            )
        return StrategyProposal(
            proposal_id=proposal_id,
            title="No discoverable strategy",
            rules={},
            evidence=[],
            created_at=datetime.now(UTC).isoformat(),
        )

    def validate(self, proposal: StrategyProposal, evidence: list[str]) -> bool:
        required = {"BACKTEST_PASS", "WALK_FORWARD_PASS", "SHADOW_PASS"}
        return required.issubset(set(evidence)) and bool(proposal.rules)

    def promote(self, proposal: StrategyProposal, evidence: list[str]) -> bool:
        if not self.validate(proposal, evidence):
            return False
        proposal.status = "PROMOTED"
        return True
