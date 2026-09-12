"""Research evolution engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ResearchEvolutionReport:
    valuable_areas: list[str]
    abandoned_areas: list[str]
    emerging_patterns: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "valuable_areas": self.valuable_areas,
            "abandoned_areas": self.abandoned_areas,
            "emerging_patterns": self.emerging_patterns,
            "timestamp": self.timestamp,
        }


class ResearchEvolutionEngine:
    def evaluate(self, *, research_results: list[dict]) -> ResearchEvolutionReport:
        valuable = [r.get("factor", "") for r in research_results if r.get("result") == "VALIDATED"]
        abandoned = [
            r.get("factor", "")
            for r in research_results
            if r.get("result") in ("REJECTED", "INSUFFICIENT")
        ]
        emerging = [r.get("factor", "") for r in research_results if r.get("result") == "TESTING"]
        return ResearchEvolutionReport(
            list(dict.fromkeys(valuable)),
            list(dict.fromkeys(abandoned)),
            list(dict.fromkeys(emerging)),
        )
