"""Multi-agent coordinator. Agents cannot place orders or modify risk."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class AgentDecision:
    market_view: str
    strategy_proposal: str
    risk_view: str
    final_decision: str
    confidence: Decimal


class AgentCoordinator:
    def coordinate(
        self, *, market_opinion: str, strategy_proposal: str, risk_decision: str
    ) -> AgentDecision:
        if risk_decision == "REJECT":
            final = "NO_TRADE"
            confidence = Decimal("0")
        elif risk_decision == "REDUCE":
            final = strategy_proposal if strategy_proposal != "NO_TRADE" else "NO_TRADE"
            confidence = Decimal("0.5")
        elif market_opinion == strategy_proposal:
            final = strategy_proposal
            confidence = Decimal("0.8")
        else:
            final = "NO_TRADE"
            confidence = Decimal("0.2")
        return AgentDecision(
            market_view=market_opinion,
            strategy_proposal=strategy_proposal,
            risk_view=risk_decision,
            final_decision=final,
            confidence=confidence,
        )
