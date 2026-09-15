"""Recommendation layer for model evidence (Low-Risk V2 Phase 3).

This evolves the existing ``ai_decision`` fusion/conflict layer into an honest
recommendation consumer of the 25-model evidence package. It is structurally
incapable of placing an order: it returns a ``TradingRecommendation`` with
``authority="RECOMMENDATION_ONLY"`` and ``not_an_order=True``. Core LLM
authority remains the only path to new risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from crypto_trader.ai_decision.correlation import RollingScoreCorrelation
from crypto_trader.factors.expert.engine import build_consensus
from crypto_trader.factors.expert.types import (
    REQUIRED_MODELS,
    EvidenceDirection,
    ModelEvidence,
    reliability_for_samples,
)

STRATEGY_HINTS = {
    "TREND": ("TREND_FOLLOWING", "PULLBACK"),
    "MOMENTUM": ("MOMENTUM", "BREAKOUT"),
    "MEAN_REVERSION": ("MEAN_REVERSION", "VWAP_REVERSION", "SUPPORT_REBOUND"),
    "VOLATILITY": ("BREAKOUT",),
    "VOLUME_FLOW": ("BREAKOUT", "MOMENTUM"),
    "ORDER_FLOW": ("MOMENTUM", "BREAKOUT"),
    "POSITIONING": ("PULLBACK",),
    "REGIME": (),
    "META": (),
}


@dataclass(slots=True)
class TradingRecommendation:
    symbol: str
    suggested_direction: str
    score: float
    confidence: float
    long_count: int
    short_count: int
    neutral_count: int
    unavailable_count: int
    raw_consensus_score: float
    correlation_adjusted_score: float
    effective_independent_evidence: int
    family_consensus: dict[str, float]
    strongest_support: list[str]
    strongest_counterarguments: list[str]
    raw_opposition: list[str]
    growth_reliability: dict[str, dict[str, Any]]
    regime_compatibility: dict[str, list[str]]
    strategy_fit: list[str]
    data_quality: str
    degraded_reasons: list[str]
    correlation: dict[str, Any]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    authority: str = "RECOMMENDATION_ONLY"
    not_an_order: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "suggested_direction": self.suggested_direction,
            "score": round(self.score, 6),
            "confidence": round(self.confidence, 6),
            "long_count": self.long_count,
            "short_count": self.short_count,
            "neutral_count": self.neutral_count,
            "unavailable_count": self.unavailable_count,
            "raw_consensus_score": round(self.raw_consensus_score, 6),
            "correlation_adjusted_score": round(self.correlation_adjusted_score, 6),
            "effective_independent_evidence": self.effective_independent_evidence,
            "family_consensus": {k: round(v, 6) for k, v in self.family_consensus.items()},
            "strongest_support": list(self.strongest_support),
            "strongest_counterarguments": list(self.strongest_counterarguments),
            "raw_opposition": list(self.raw_opposition),
            "growth_reliability": {k: dict(v) for k, v in self.growth_reliability.items()},
            "regime_compatibility": {k: list(v) for k, v in self.regime_compatibility.items()},
            "strategy_fit": list(self.strategy_fit),
            "data_quality": self.data_quality,
            "degraded_reasons": list(self.degraded_reasons),
            "correlation": dict(self.correlation),
            "generated_at": self.generated_at,
            "authority": self.authority,
            "not_an_order": self.not_an_order,
        }


class RecommendationEngine:
    """Build an auditable recommendation from the 25-model evidence package."""

    def __init__(
        self,
        *,
        correlation: RollingScoreCorrelation | None = None,
        direction_threshold: float = 0.15,
    ) -> None:
        self.correlation = correlation or RollingScoreCorrelation()
        self.direction_threshold = float(direction_threshold)
        self.last_recommendation: TradingRecommendation | None = None

    def build(self, package: dict[str, Any]) -> TradingRecommendation:
        models_raw = package.get("models") or {}
        evidence: list[ModelEvidence] = []
        reliability: dict[str, dict[str, Any]] = {}
        regime_compat: dict[str, list[str]] = {}
        strategy_fit: list[str] = []
        for model_id, item in models_raw.items():
            spec = next((spec for spec in REQUIRED_MODELS if spec.model_id == model_id), None)
            if spec is None or not isinstance(item, dict):
                continue
            evidence.append(
                ModelEvidence(
                    model_id=spec.model_id,
                    model_version=str(item.get("model_version", spec.version)),
                    family=spec.family,
                    symbol=str(item.get("symbol", package.get("symbol", ""))),
                    timeframes=tuple(item.get("timeframes") or spec.timeframes),
                    direction=EvidenceDirection(item.get("direction", "UNAVAILABLE")),
                    direction_score=float(item.get("direction_score", 0.0)),
                    confidence=float(item.get("confidence", 0.0)),
                    theory=str(item.get("theory", spec.description)),
                    supporting_evidence=list(item.get("supporting_evidence") or []),
                    counter_evidence=list(item.get("counter_evidence") or []),
                    neutral_evidence=list(item.get("neutral_evidence") or []),
                    regime_compatibility=list(item.get("regime_compatibility") or []),
                    strategy_compatibility=list(item.get("strategy_compatibility") or []),
                    data_quality=item.get("data_quality", "UNAVAILABLE"),
                    sample_size=int(item.get("sample_size", 0) or 0),
                )
            )
            samples = int(item.get("sample_size", 0) or 0)
            reliability[model_id] = {
                "sample_size": samples,
                "tier": str(item.get("reliability_tier") or reliability_for_samples(samples)),
            }
            regime_compat[model_id] = list(item.get("regime_compatibility") or [])
            for strategy in item.get("strategy_compatibility") or []:
                if strategy not in strategy_fit and strategy != "*":
                    strategy_fit.append(strategy)
        regime = str(package.get("regime", "UNCERTAIN"))
        consensus = build_consensus(regime, evidence)

        available = [item for item in evidence if item.available]
        scores = {item.model_id: item.direction_score for item in available}
        if scores:
            self.correlation.record(scores)
        observed_clusters = self.correlation.effective_independent_count(list(scores))
        # Family collapsing is the baseline independence control; observed
        # correlation clusters can only reduce it further (they never inflate
        # breadth beyond the number of families with directional evidence).
        if observed_clusters == 0:
            independent = consensus.effective_independent_evidence
        else:
            independent = min(consensus.effective_independent_evidence, observed_clusters)

        # Combine raw and correlation-adjusted consensus, then damp by evidence
        # breadth so a single loud model cannot dominate the recommendation.
        breadth = min(1.0, independent / 5.0)
        score = (0.5 * consensus.raw_score + 0.5 * consensus.correlation_adjusted_score) * (
            0.5 + 0.5 * breadth
        )
        if score > self.direction_threshold:
            direction = EvidenceDirection.LONG.value
        elif score < -self.direction_threshold:
            direction = EvidenceDirection.SHORT.value
        else:
            direction = EvidenceDirection.NEUTRAL.value
        confidence = max(
            0.0,
            min(
                1.0,
                abs(score) * 0.6
                + breadth * 0.2
                + (0.2 if consensus.data_quality == "HEALTHY" else 0.0),
            ),
        )
        degraded: list[str] = []
        for model_id, item in models_raw.items():
            if item.get("direction") == EvidenceDirection.UNAVAILABLE.value:
                degraded.append(f"{model_id}:{item.get('unavailable_reason') or 'UNAVAILABLE'}")
        recommendation = TradingRecommendation(
            symbol=str(package.get("symbol", "")),
            suggested_direction=direction,
            score=score,
            confidence=confidence,
            long_count=consensus.long_count,
            short_count=consensus.short_count,
            neutral_count=consensus.neutral_count,
            unavailable_count=consensus.unavailable_count,
            raw_consensus_score=consensus.raw_score,
            correlation_adjusted_score=consensus.correlation_adjusted_score,
            effective_independent_evidence=independent,
            family_consensus=dict(consensus.family_votes),
            strongest_support=list(consensus.strongest_support),
            strongest_counterarguments=list(consensus.strongest_counterarguments),
            raw_opposition=list(consensus.raw_opposition),
            growth_reliability=reliability,
            regime_compatibility=regime_compat,
            strategy_fit=strategy_fit,
            data_quality=consensus.data_quality,
            degraded_reasons=degraded,
            correlation=self.correlation.as_dict(),
        )
        self.last_recommendation = recommendation
        return recommendation


def strategy_hints_for_family(family: str) -> tuple[str, ...]:
    return STRATEGY_HINTS.get(family, ())
