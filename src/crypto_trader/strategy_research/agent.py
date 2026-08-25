"""AI strategy research agent: discovers hypotheses only, never promotes directly."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchProposal:
    proposal_id: str
    symbol: str
    hypothesis: str
    evidence: list[str]
    validation_plan: list[str] = field(
        default_factory=lambda: ["BACKTEST", "PAPER", "SHADOW", "APPROVAL"]
    )
    status: str = "PROPOSED"


class StrategyResearchAgent:
    def research(self, proposal_id: str, symbol: str, pattern: str) -> ResearchProposal:
        return ResearchProposal(
            proposal_id=proposal_id,
            symbol=symbol,
            hypothesis=f"{symbol} {pattern} may improve breakout success",
            evidence=[f"{symbol}_orderflow_early", f"{symbol}_vol_trend"],
        )
