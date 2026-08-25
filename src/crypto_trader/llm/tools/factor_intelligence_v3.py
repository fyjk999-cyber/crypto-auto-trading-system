"""Factor Intelligence v3 LLM tools: regime, confidence, combinations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.factors.combinations.evaluator import CombinationEvaluator
from crypto_trader.factors.confidence import FactorConfidenceEngine
from crypto_trader.factors.regime.classifier import RegimeClassifier


@dataclass
class FactorV3ToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorIntelligenceV3Tools:
    def __init__(self) -> None:
        self._confidence_engine = FactorConfidenceEngine()
        self._regime_classifier = RegimeClassifier()
        self._combination_evaluator = CombinationEvaluator()

    async def get_market_regime(
        self, symbol: str, factor_snapshot: dict | None = None
    ) -> FactorV3ToolResult:
        if factor_snapshot is None:
            return FactorV3ToolResult(
                True,
                {"symbol": symbol, "regime": "UNKNOWN", "confidence": 0.0, "evidence": []},
                None,
            )
        try:
            regime = self._regime_classifier.classify(symbol, factor_snapshot)
            return FactorV3ToolResult(True, regime, None)
        except Exception as exc:
            return FactorV3ToolResult(False, {}, f"REGIME_UNAVAILABLE:{type(exc).__name__}")

    async def get_factor_confidence(
        self,
        factor: str,
        current_value: Decimal,
        historical_reliability: Decimal,
        regime_match: Decimal,
        decay_status: str = "HEALTHY",
    ) -> FactorV3ToolResult:
        result = self._confidence_engine.compute(
            factor=factor,
            current_value=current_value,
            historical_reliability=historical_reliability,
            regime_match=regime_match,
            decay_status=decay_status,
        )
        return FactorV3ToolResult(True, result.to_dict(), None)

    async def get_best_factor_context(
        self, symbol: str, factor_snapshot: dict, confidences: list[dict]
    ) -> FactorV3ToolResult:
        try:
            regime = self._regime_classifier.classify(symbol, factor_snapshot)
            confidences = sorted(
                confidences, key=lambda c: float(c.get("confidence", 0)), reverse=True
            )
            reliable = [c for c in confidences if float(c.get("confidence", 0)) >= 0.5]
            weak = [c for c in confidences if float(c.get("confidence", 0)) < 0.5]
            return FactorV3ToolResult(
                True,
                {
                    "symbol": symbol,
                    "regime": regime,
                    "reliable_factors": reliable,
                    "weak_factors": weak,
                },
                None,
            )
        except Exception as exc:
            return FactorV3ToolResult(False, {}, f"BEST_CONTEXT_UNAVAILABLE:{type(exc).__name__}")

    async def analyze_factor_combination(
        self, factors: list[str], observations: list[dict]
    ) -> FactorV3ToolResult:
        combination = self._combination_evaluator.evaluate(
            factors=factors, observations=observations
        )
        return FactorV3ToolResult(True, combination.to_dict(), None)
