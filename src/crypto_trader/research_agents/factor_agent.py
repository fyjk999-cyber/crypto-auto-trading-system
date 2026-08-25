"""Factor research agent."""

from __future__ import annotations

from crypto_trader.research_agents.models import AgentReport


class FactorAgent:
    def analyze(
        self, factor_performance: dict | None = None, factor_importance: dict | None = None
    ) -> AgentReport:
        perf = factor_performance or {}
        imp = factor_importance or {}
        if not perf and not imp:
            return (AgentReport("factor", "no factor data", 0.2, ["missing"]),)
        strong = (
            [k for k, v in perf.items() if float(v.get("win_rate", 0)) > 0.55]
            if isinstance(perf, dict)
            else []
        )
        weak = (
            [k for k, v in perf.items() if float(v.get("win_rate", 0)) < 0.45]
            if isinstance(perf, dict)
            else []
        )
        finding = "strong factors: " + ",".join(strong) if strong else "no strong factors"
        confidence = min(0.9, 0.4 + len(strong) * 0.1)
        return AgentReport("factor", finding, confidence, strong + weak)
