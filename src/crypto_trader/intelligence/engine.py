"""Market intelligence engine: orchestrates summary/consensus/similarity."""

from __future__ import annotations

from crypto_trader.domain.money import D
from crypto_trader.intelligence.confidence import IntelligenceConfidence
from crypto_trader.intelligence.context_builder import MarketIntelligenceContextBuilder
from crypto_trader.intelligence.summary import MarketSummaryEngine
from crypto_trader.research.consensus import ResearchConsensusEngine


class MarketIntelligenceEngine:
    def __init__(self) -> None:
        self.summary_engine = MarketSummaryEngine()
        self.consensus_engine = ResearchConsensusEngine()
        self.confidence_engine = IntelligenceConfidence()
        self.builder = MarketIntelligenceContextBuilder()

    def build(
        self,
        *,
        symbol: str,
        regime: dict,
        factors: dict,
        factor_confidences: dict,
        anomalies: list[dict] | None = None,
        research: list[dict] | None = None,
        similar_cases: dict | None = None,
    ) -> dict:
        summary = self.summary_engine.summarize(
            regime=regime, factors=factors, anomalies=anomalies or [], research=research
        )
        consensus = self.consensus_engine.consensus(research or [])
        confidence_values = (
            [D(str(c.get("confidence", "0"))) for c in factor_confidences.values()]
            if isinstance(factor_confidences, dict)
            else [D(str(c.get("confidence", "0"))) for c in factor_confidences]
        )
        avg_factor_confidence = (
            sum(confidence_values, D("0")) / D(str(len(confidence_values)))
            if confidence_values
            else D("0")
        )
        overall = self.confidence_engine.compute(
            regime_confidence=D(str(regime.get("confidence", "0.5"))),
            factor_confidence_avg=avg_factor_confidence,
            research_consensus_confidence=D(str(consensus.get("confidence", "0.5"))),
            data_quality=D("0.8"),
        )
        context = self.builder.build(
            symbol=symbol,
            regime=regime,
            summary=summary.to_dict(),
            confidence={k: v for k, v in factor_confidences.items()}
            if isinstance(factor_confidences, dict)
            else {},
            positive_evidence=summary.supporting,
            negative_evidence=summary.risks,
            research_summary=consensus,
            similarity=similar_cases or {},
            overall_confidence=float(overall),
        )
        return context.to_dict()
