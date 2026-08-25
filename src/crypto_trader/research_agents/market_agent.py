"""Market research agent."""

from __future__ import annotations

from crypto_trader.research_agents.models import AgentReport


class MarketAgent:
    def analyze(
        self,
        regime: dict | None = None,
        anomalies: list | None = None,
        similarity: dict | None = None,
    ) -> AgentReport:
        regime = regime or {}
        anomalies = anomalies or []
        similarity = similarity or {}
        finding = f"regime {regime.get('regime', 'UNKNOWN')}"
        confidence = float(regime.get("confidence", 0.4))
        if anomalies:
            finding += " with anomalies"
        return AgentReport(
            "market", finding, confidence, [a.get("type", "anomaly") for a in anomalies]
        )
