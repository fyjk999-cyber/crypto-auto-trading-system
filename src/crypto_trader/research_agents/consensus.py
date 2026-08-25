"""Research consensus engine."""

from __future__ import annotations

from crypto_trader.research_agents.models import ResearchConsensus


class ResearchConsensusEngine:
    def combine(self, reports: list) -> ResearchConsensus:
        bull = []
        bear = []
        uncertainty = []
        for r in reports:
            if r.agent == "risk" and r.confidence < 0.5:
                bear.append(r.finding)
                uncertainty.append(r.agent)
            elif r.confidence >= 0.5:
                bull.append(r.finding)
            else:
                bear.append(r.finding)
                uncertainty.append(r.agent)
        conf = sum(r.confidence for r in reports) / len(reports) if reports else 0.0
        return ResearchConsensus(bull, bear, uncertainty, round(conf, 3))
