"""Market intelligence LLM tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.intelligence.engine import MarketIntelligenceEngine
from crypto_trader.intelligence.knowledge.graph import KnowledgeGraph
from crypto_trader.intelligence.similarity.matcher import SimilarityMatcher
from crypto_trader.research.consensus import ResearchConsensusEngine


@dataclass
class MarketIntelligenceToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class MarketIntelligenceTools:
    def __init__(self) -> None:
        self._engine = MarketIntelligenceEngine()
        self._matcher = SimilarityMatcher()
        self._consensus = ResearchConsensusEngine()
        self._knowledge = KnowledgeGraph()

    async def get_market_intelligence(
        self,
        symbol: str,
        *,
        regime: dict,
        factors: dict,
        factor_confidences: dict,
        anomalies: list[dict] | None = None,
        research: list[dict] | None = None,
        similar_cases: dict | None = None,
    ) -> MarketIntelligenceToolResult:
        try:
            context = self._engine.build(
                symbol=symbol,
                regime=regime,
                factors=factors,
                factor_confidences=factor_confidences,
                anomalies=anomalies,
                research=research,
                similar_cases=similar_cases,
            )
            return MarketIntelligenceToolResult(True, context, None)
        except Exception as exc:
            return MarketIntelligenceToolResult(
                False, {}, f"INTELLIGENCE_UNAVAILABLE:{type(exc).__name__}"
            )

    async def get_market_summary(
        self, symbol: str, *, regime: dict, factors: dict, anomalies: list[dict]
    ) -> MarketIntelligenceToolResult:
        summary = self._engine.summary_engine.summarize(
            regime=regime, factors=factors, anomalies=anomalies
        )
        return MarketIntelligenceToolResult(True, summary.to_dict(), None)

    async def get_similar_market_cases(
        self,
        symbol: str,
        *,
        current_regime: str,
        current_factors: dict,
        historical_cases: list[dict],
    ) -> MarketIntelligenceToolResult:
        result = self._matcher.match(
            current_regime=current_regime,
            current_factors=current_factors,
            historical_cases=historical_cases,
        )
        return MarketIntelligenceToolResult(True, result, None)

    async def get_research_consensus(
        self, symbol: str, research: list[dict]
    ) -> MarketIntelligenceToolResult:
        result = self._consensus.consensus(research)
        return MarketIntelligenceToolResult(True, result, None)

    async def query_market_knowledge(self, question: str) -> MarketIntelligenceToolResult:
        result = self._knowledge.query(question)
        return MarketIntelligenceToolResult(True, result, None)

    def add_knowledge_relation(
        self, entity_a: str, relation: str, entity_b: str, metadata: dict | None = None
    ) -> None:
        self._knowledge.add(entity_a, relation, entity_b, metadata)
