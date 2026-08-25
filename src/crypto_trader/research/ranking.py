"""Research priority ranking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResearchPriority:
    hypothesis_id: str
    score: float
    rank: int = 0

    def to_dict(self) -> dict:
        return {"hypothesis_id": self.hypothesis_id, "score": self.score, "rank": self.rank}


class ResearchRanker:
    def rank(self, hypotheses: list[dict]) -> list[ResearchPriority]:
        scored = []
        for h in hypotheses:
            score = (
                0.25 * float(h.get("confidence", 0))
                + 0.25 * float(h.get("market_relevance", 0.5))
                + 0.2 * float(h.get("data_quality", 0.5))
                + 0.15 * float(h.get("novelty", 0.5))
                + 0.15 * float(h.get("potential_value", 0.5))
            )
            scored.append(ResearchPriority(h.get("id", ""), round(score, 3)))
        scored.sort(key=lambda p: p.score, reverse=True)
        for rank, item in enumerate(scored, start=1):
            item.rank = rank
        return scored
