"""Research agents LLM tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.research_agents.supervisor import ResearchSupervisor


@dataclass
class ResearchAgentToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ResearchAgentTools:
    def __init__(self) -> None:
        self.supervisor = ResearchSupervisor()
        self.latest: dict = {}

    async def get_agent_reports(
        self,
        *,
        factor_performance=None,
        factor_importance=None,
        regime=None,
        anomalies=None,
        similarity=None,
        volatility=0.0,
        drawdown_env=0.0,
        uncertainty=0.0,
    ) -> ResearchAgentToolResult:
        package = self.supervisor.run(
            factor_performance=factor_performance,
            factor_importance=factor_importance,
            regime=regime,
            anomalies=anomalies,
            similarity=similarity,
            volatility=volatility,
            drawdown_env=drawdown_env,
            uncertainty=uncertainty,
        )
        self.latest = package
        return ResearchAgentToolResult(True, package["reports"], None)

    async def get_research_consensus(self) -> ResearchAgentToolResult:
        if not self.latest:
            return ResearchAgentToolResult(True, {}, None)
        return ResearchAgentToolResult(True, self.latest["consensus"], None)

    async def get_agent_confidence(self) -> ResearchAgentToolResult:
        if not self.latest:
            return ResearchAgentToolResult(True, {}, None)
        return ResearchAgentToolResult(True, self.latest["agent_confidence"], None)
