"""LLM context builder and output contract. LLM cannot submit orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: str  # LONG | SHORT | NO_TRADE
    confidence: float
    risk_level: str
    reason_codes: list[str] = Field(default_factory=list)
    invalid_conditions: list[str] = Field(default_factory=list)


@dataclass
class LLMContext:
    symbol: str
    market_state: dict
    feature_vector: dict
    position_state: dict
    risk_state: dict
    trade_memory: list[dict] = field(default_factory=list)
    daily_review: dict = field(default_factory=dict)
    factor_snapshot: dict = field(default_factory=dict)
    factor_health: dict = field(default_factory=dict)
    market_regime: dict = field(default_factory=dict)
    factor_confidence: dict = field(default_factory=dict)
    factor_combinations: dict = field(default_factory=dict)
    market_anomaly: dict = field(default_factory=dict)
    active_research: dict = field(default_factory=dict)
    previous_findings: dict = field(default_factory=dict)
    historical_similarity: dict = field(default_factory=dict)
    research_consensus: dict = field(default_factory=dict)
    market_intelligence_summary: dict = field(default_factory=dict)
    factor_lifecycle: dict = field(default_factory=dict)
    research_priority: dict = field(default_factory=dict)
    factor_importance: dict = field(default_factory=dict)
    knowledge_health: dict = field(default_factory=dict)
    factor_performance: dict = field(default_factory=dict)
    prepared_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class LLMContextBuilder:
    def build(
        self,
        *,
        symbol: str,
        market_state: dict | None = None,
        feature_vector: dict | None = None,
        position_state: dict | None = None,
        risk_state: dict | None = None,
        trade_memory: list[dict] | None = None,
        daily_review: dict | None = None,
        factor_snapshot: dict | None = None,
        factor_health: dict | None = None,
        factor_performance: dict | None = None,
        market_regime: dict | None = None,
        factor_confidence: dict | None = None,
        factor_combinations: dict | None = None,
        market_anomaly: dict | None = None,
        active_research: dict | None = None,
        previous_findings: dict | None = None,
        historical_similarity: dict | None = None,
        research_consensus: dict | None = None,
        market_intelligence_summary: dict | None = None,
        factor_lifecycle: dict | None = None,
        research_priority: dict | None = None,
        factor_importance: dict | None = None,
        knowledge_health: dict | None = None,
    ) -> LLMContext:
        return LLMContext(
            symbol=symbol,
            market_state=market_state or {},
            feature_vector=feature_vector or {},
            position_state=position_state or {},
            risk_state=risk_state or {},
            trade_memory=trade_memory or [],
            daily_review=daily_review or {},
            factor_snapshot=factor_snapshot or {},
            factor_health=factor_health or {},
            factor_performance=factor_performance or {},
            market_regime=market_regime or {},
            factor_confidence=factor_confidence or {},
            factor_combinations=factor_combinations or {},
            market_anomaly=market_anomaly or {},
            active_research=active_research or {},
            previous_findings=previous_findings or {},
            historical_similarity=historical_similarity or {},
            research_consensus=research_consensus or {},
            market_intelligence_summary=market_intelligence_summary or {},
            factor_lifecycle=factor_lifecycle or {},
            research_priority=research_priority or {},
            factor_importance=factor_importance or {},
            knowledge_health=knowledge_health or {},
        )

    def render_prompt(self, ctx: LLMContext) -> str:
        return (
            f"You are a crypto market analyst. Return JSON only. Symbol: {ctx.symbol}\n"
            f"MarketState: {ctx.market_state}\nFeatures: {ctx.feature_vector}\n"
            f"Factors: {ctx.factor_snapshot}\n"
            f"FactorHealth: {ctx.factor_health}\n"
            f"FactorPerformance: {ctx.factor_performance}\n"
            f"MarketRegime: {ctx.market_regime}\n"
            f"FactorConfidence: {ctx.factor_confidence}\n"
            f"FactorCombinations: {ctx.factor_combinations}\n"
            f"MarketAnomaly: {ctx.market_anomaly}\n"
            f"ActiveResearch: {ctx.active_research}\n"
            f"PreviousFindings: {ctx.previous_findings}\n"
            f"HistoricalSimilarity: {ctx.historical_similarity}\n"
            f"ResearchConsensus: {ctx.research_consensus}\n"
            f"MarketIntelligenceSummary: {ctx.market_intelligence_summary}\n"
            f"FactorLifecycle: {ctx.factor_lifecycle}\n"
            f"ResearchPriority: {ctx.research_priority}\n"
            f"FactorImportance: {ctx.factor_importance}\n"
            f"KnowledgeHealth: {ctx.knowledge_health}\n"
            f"Risk: {ctx.risk_state}\n"
            "Output keys: direction, confidence, risk_level, reason_codes, invalid_conditions."
        )


def parse_llm_output(payload: dict) -> LLMOutput:
    return LLMOutput(**payload)
