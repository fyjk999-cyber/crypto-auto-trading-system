"""Research optimizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ResearchStrategy:
    focus_areas: list[str]
    resource_allocation: dict[str, float]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "focus_areas": self.focus_areas,
            "resource_allocation": self.resource_allocation,
            "timestamp": self.timestamp,
        }


class ResearchOptimizer:
    def optimize(self, research_items: list[dict]) -> ResearchStrategy:
        ranked = sorted(
            research_items,
            key=lambda r: (
                r.get("value", 0) * 0.4
                + r.get("confidence", 0) * 0.3
                + r.get("novelty", 0) * 0.15
                + r.get("impact", 0) * 0.15
            ),
            reverse=True,
        )
        focus = [r.get("research_id", "") for r in ranked[:3]]
        allocation = {
            r.get("research_id", ""): round(0.5 / (i + 1), 3) for i, r in enumerate(ranked[:3])
        }
        return ResearchStrategy(focus_areas=focus, resource_allocation=allocation)
