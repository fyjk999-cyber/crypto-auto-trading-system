"""Adaptive factor intelligence LLM tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.factors.importance import FactorImportanceEngine
from crypto_trader.factors.lifecycle.manager import FactorLifecycleManager
from crypto_trader.intelligence.knowledge.decay import KnowledgeDecayEngine
from crypto_trader.research.priority import ResearchPriorityEngine


@dataclass
class AdaptiveIntelligenceToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AdaptiveIntelligenceTools:
    def __init__(self) -> None:
        self._lifecycle = FactorLifecycleManager()
        self._priority = ResearchPriorityEngine()
        self._importance = FactorImportanceEngine()
        self._decay = KnowledgeDecayEngine()

    async def get_factor_lifecycle(
        self,
        factor: str,
        *,
        current_state: str,
        sample_size: int,
        win_rate: Decimal,
        sharpe: Decimal,
        decay_status: str,
    ) -> AdaptiveIntelligenceToolResult:
        result = self._lifecycle.evaluate(
            factor=factor,
            current_state=current_state,
            sample_size=sample_size,
            win_rate=win_rate,
            sharpe=sharpe,
            decay_status=decay_status,
        )
        return AdaptiveIntelligenceToolResult(True, result.to_dict(), None)

    async def get_research_priority(
        self,
        research_id: str,
        *,
        market_relevance: float,
        anomaly_severity: float,
        novelty: float,
        confidence: float,
        potential_impact: float,
    ) -> AdaptiveIntelligenceToolResult:
        result = self._priority.evaluate(
            research_id=research_id,
            market_relevance=market_relevance,
            anomaly_severity=anomaly_severity,
            novelty=novelty,
            confidence=confidence,
            potential_impact=potential_impact,
        )
        return AdaptiveIntelligenceToolResult(True, result.to_dict(), None)

    async def get_factor_importance(self, factors: list[dict]) -> AdaptiveIntelligenceToolResult:
        results = self._importance.compute(factors)
        return AdaptiveIntelligenceToolResult(True, [r.to_dict() for r in results], None)

    async def get_knowledge_health(
        self,
        knowledge_id: str,
        *,
        age_days: float,
        performance_change: float,
        regime_change: float,
        contradiction_frequency: float,
    ) -> AdaptiveIntelligenceToolResult:
        result = self._decay.evaluate(
            knowledge_id=knowledge_id,
            age_days=age_days,
            performance_change=performance_change,
            regime_change=regime_change,
            contradiction_frequency=contradiction_frequency,
        )
        return AdaptiveIntelligenceToolResult(True, result.to_dict(), None)
