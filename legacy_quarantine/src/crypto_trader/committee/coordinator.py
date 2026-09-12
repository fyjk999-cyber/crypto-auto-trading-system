"""Multi-agent trading committee and debate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentOutput:
    agent: str
    opinion: str
    confidence: float
    reason: str


@dataclass
class DebateReport:
    bull_opinion: AgentOutput
    bear_opinion: AgentOutput
    final_decision: str
    final_confidence: float


class TradingCommittee:
    def debate(
        self, *, research_view: str, quant_view: str, risk_view: str, conviction: float
    ) -> DebateReport:
        bull = AgentOutput("Bull Agent", research_view, max(0.5, conviction), "upside")
        bear = AgentOutput("Bear Agent", risk_view, 1 - conviction, "downside")
        final = "LONG" if conviction >= 0.6 and risk_view != "REJECT" else "NO_TRADE"
        final_conf = conviction if final == "LONG" else 0.2
        return DebateReport(
            bull_opinion=bull, bear_opinion=bear, final_decision=final, final_confidence=final_conf
        )
