"""Research supervisor."""

from __future__ import annotations

from crypto_trader.research_agents.consensus import ResearchConsensusEngine
from crypto_trader.research_agents.factor_agent import FactorAgent
from crypto_trader.research_agents.market_agent import MarketAgent
from crypto_trader.research_agents.risk_agent import RiskAgent


class ResearchSupervisor:
    def __init__(self) -> None:
        self.factor_agent = FactorAgent()
        self.market_agent = MarketAgent()
        self.risk_agent = RiskAgent()
        self.consensus_engine = ResearchConsensusEngine()

    def run(
        self,
        *,
        factor_performance: dict | None = None,
        factor_importance: dict | None = None,
        regime: dict | None = None,
        anomalies: list | None = None,
        similarity: dict | None = None,
        volatility: float = 0.0,
        drawdown_env: float = 0.0,
        uncertainty: float = 0.0,
    ) -> dict:
        reports = [
            self.factor_agent.analyze(factor_performance, factor_importance),
            self.market_agent.analyze(regime, anomalies, similarity),
            self.risk_agent.analyze(volatility, drawdown_env, uncertainty),
        ]
        consensus = self.consensus_engine.combine(reports)
        return {
            "reports": [r.to_dict() for r in reports],
            "consensus": consensus.to_dict(),
            "agent_confidence": {r.agent: r.confidence for r in reports},
        }
