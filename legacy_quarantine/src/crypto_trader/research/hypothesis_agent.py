"""Research hypothesis agent: converts anomalies into research questions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ResearchHypothesis:
    id: str
    question: str
    factor: str
    logic: str
    expected_behavior: str
    confidence: float
    created_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "factor": self.factor,
            "logic": self.logic,
            "expected_behavior": self.expected_behavior,
            "confidence": self.confidence,
            "created_time": self.created_time,
        }


class HypothesisAgent:
    def generate(
        self, hypothesis_id: str, anomaly: dict, factor_history: list | None = None
    ) -> ResearchHypothesis:
        anomaly_type = anomaly.get("type", "unknown")
        symbol = anomaly.get("symbol", "")
        if anomaly_type == "orderflow_failure":
            return ResearchHypothesis(
                hypothesis_id,
                f"Strong orderflow without price expansion in {symbol} "
                f"may predict short-term reversal",
                "orderflow",
                "buy pressure with stagnant price",
                "price reverses down",
                0.6,
            )
        if anomaly_type == "price_volume_divergence":
            return ResearchHypothesis(
                hypothesis_id,
                f"Price/volume divergence in {symbol} weakens trend reliability",
                "volume",
                "price up volume down",
                "trend fades",
                0.55,
            )
        if anomaly_type == "oi_divergence":
            return ResearchHypothesis(
                hypothesis_id,
                f"OI divergence in {symbol} predicts weaker continuation",
                "open_interest",
                "price up OI down",
                "continuation fails",
                0.5,
            )
        if anomaly_type == "funding_extreme":
            return ResearchHypothesis(
                hypothesis_id,
                f"Extreme funding in {symbol} predicts crowded positioning and reversal risk",
                "funding",
                "funding extreme",
                "reversal probability rises",
                0.65,
            )
        if anomaly_type == "volatility_regime_shift":
            return ResearchHypothesis(
                hypothesis_id,
                f"Volatility regime shift in {symbol} changes factor reliability",
                "volatility",
                "low vol to high vol",
                "trend/momentum factors degrade",
                0.6,
            )
        return ResearchHypothesis(
            hypothesis_id,
            f"Anomaly {anomaly_type} in {symbol}",
            "unknown",
            anomaly_type,
            "needs validation",
            0.4,
        )
