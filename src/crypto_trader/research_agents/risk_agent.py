"""Risk research agent."""

from __future__ import annotations

from crypto_trader.research_agents.models import AgentReport


class RiskAgent:
    def analyze(
        self, volatility: float = 0.0, drawdown_env: float = 0.0, uncertainty: float = 0.0
    ) -> AgentReport:
        risk = 0.3 * min(1.0, volatility) + 0.4 * min(1.0, drawdown_env) + 0.3 * uncertainty
        if risk > 0.6:
            finding = "elevated risk environment"
        elif risk > 0.3:
            finding = "moderate risk environment"
        else:
            finding = "low risk environment"
        return AgentReport(
            "risk",
            finding,
            round(1 - risk, 3),
            [f"volatility={volatility}", f"drawdown_env={drawdown_env}"],
        )
