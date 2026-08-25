"""Research feedback builder."""

from __future__ import annotations

from crypto_trader.intelligence.feedback.models import ResearchFeedback


class ResearchFeedbackBuilder:
    def build(
        self,
        *,
        symbol: str,
        market_intelligence: dict,
        factor_confidences: dict,
        research_consensus: dict,
        historical_context: dict,
        knowledge_health: dict,
    ) -> ResearchFeedback:
        regime = market_intelligence.get("market_regime", {})
        market_state = regime.get("regime", "UNKNOWN") if isinstance(regime, dict) else str(regime)
        validated = []
        for factor, conf in factor_confidences.items():
            value = float(conf.get("confidence", 0)) if isinstance(conf, dict) else float(conf)
            if value >= 0.5:
                validated.append(factor)
        risk_notes = []
        for knowledge_id, health in knowledge_health.items():
            status = health.get("status", "VALID") if isinstance(health, dict) else str(health)
            if status in ("DEGRADED", "INVALID"):
                risk_notes.append(f"{knowledge_id}:{status}")
        confidence = self._confidence(factor_confidences, research_consensus, knowledge_health)
        return ResearchFeedback(
            symbol=symbol,
            market_state=market_state,
            validated_factors=validated,
            factor_confidence=factor_confidences,
            research_consensus=research_consensus,
            historical_context=historical_context,
            risk_notes=risk_notes,
            confidence=confidence,
        )

    @staticmethod
    def _confidence(factor_confidences: dict, consensus: dict, knowledge_health: dict) -> float:
        values = [
            float(c.get("confidence", 0)) if isinstance(c, dict) else float(c)
            for c in factor_confidences.values()
        ]
        factor_avg = sum(values) / len(values) if values else 0.0
        consensus_conf = float(consensus.get("confidence", 0.5))
        health_values = []
        for h in knowledge_health.values():
            status = h.get("status", "VALID") if isinstance(h, dict) else h
            health_values.append(1.0 if status == "VALID" else 0.5)
        health_avg = sum(health_values) / len(health_values) if health_values else 1.0
        return round(0.5 * factor_avg + 0.3 * consensus_conf + 0.2 * health_avg, 3)
