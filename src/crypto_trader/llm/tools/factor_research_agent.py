"""Autonomous factor research agent tools for LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.factors.anomaly.detector import MarketAnomalyDetector
from crypto_trader.research.experiment_planner import ExperimentPlanner
from crypto_trader.research.hypothesis_agent import HypothesisAgent
from crypto_trader.research.ranking import ResearchRanker


@dataclass
class ResearchAgentToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorResearchAgentTools:
    def __init__(self) -> None:
        self._anomaly_detector = MarketAnomalyDetector()
        self._hypothesis_agent = HypothesisAgent()
        self._planner = ExperimentPlanner()
        self._ranker = ResearchRanker()
        self._reports: dict[str, dict] = {}
        self._anomalies: list[dict] = []

    async def get_market_anomalies(
        self,
        symbol: str,
        *,
        price_change: float = 0,
        volume_change: float = 0,
        orderflow: float = 0,
        oi_change: float = 0,
        funding: float = 0,
        volatility: float = 0,
        volatility_previous: float = 0,
    ) -> ResearchAgentToolResult:
        anomalies = self._anomaly_detector.detect(
            symbol,
            price_change=str(price_change),
            volume_change=str(volume_change),
            orderflow=str(orderflow),
            oi_change=str(oi_change),
            funding=str(funding),
            volatility=str(volatility),
            volatility_previous=str(volatility_previous),
        )
        data = [a.to_dict() for a in anomalies]
        self._anomalies.extend(data)
        return ResearchAgentToolResult(True, data, None)

    async def generate_hypothesis(
        self, hypothesis_id: str, anomaly: dict
    ) -> ResearchAgentToolResult:
        hypothesis = self._hypothesis_agent.generate(hypothesis_id, anomaly)
        return ResearchAgentToolResult(True, hypothesis.to_dict(), None)

    async def create_research_experiment(self, hypothesis: dict) -> ResearchAgentToolResult:
        plan = self._planner.plan(hypothesis)
        return ResearchAgentToolResult(True, plan.to_dict(), None)

    async def get_research_priority(self, hypotheses: list[dict]) -> ResearchAgentToolResult:
        ranked = self._ranker.rank(hypotheses)
        return ResearchAgentToolResult(True, [r.to_dict() for r in ranked], None)

    async def get_research_report(self, research_id: str) -> ResearchAgentToolResult:
        report = self._reports.get(research_id)
        if report is None:
            return ResearchAgentToolResult(
                True, {"research_id": research_id, "status": "NOT_FOUND"}, None
            )
        return ResearchAgentToolResult(True, report, None)

    def store_report(self, research_id: str, report: dict) -> None:
        self._reports[research_id] = report
