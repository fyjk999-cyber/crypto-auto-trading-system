"""Factor discovery: detect potential useful factors from existing data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorCandidate:
    candidate_id: str
    name: str
    category: str
    rationale: str
    score: float
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorDiscovery:
    def discover(
        self, *, factor_id: str, observations: list[dict], behavior: str = "repeated_pattern"
    ) -> FactorCandidate:
        if behavior == "repeated_pattern":
            score = min(0.95, 0.4 + len(observations) / 100)
            return FactorCandidate(
                factor_id,
                factor_id,
                "discovered",
                "repeated pattern across similar market states",
                score,
            )
        if behavior == "factor_correlation":
            score = min(0.8, 0.3 + len(observations) / 200)
            return FactorCandidate(
                factor_id,
                factor_id,
                "discovered",
                "correlated with existing factor but provides orthogonal info",
                score,
            )
        return FactorCandidate(
            factor_id, factor_id, "discovered", "unusual market behavior detected", 0.35
        )
