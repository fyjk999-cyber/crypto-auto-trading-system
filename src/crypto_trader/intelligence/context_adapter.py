"""Analysis context adapter for LLM / analysis layer."""

from __future__ import annotations


class AnalysisContextAdapter:
    def adapt(self, feedback: dict) -> dict:
        validated = feedback.get("validated_factors", [])
        weak = [f for f in feedback.get("factor_confidence", {}) if f not in validated]
        consensus = feedback.get("research_consensus", {})
        return {
            "market": feedback.get("market_state", "UNKNOWN"),
            "trusted_factors": validated,
            "weak_factors": weak,
            "research_view": consensus.get("conclusion", "neutral"),
            "risk_notes": feedback.get("risk_notes", []),
            "confidence": feedback.get("confidence", 0.0),
        }
