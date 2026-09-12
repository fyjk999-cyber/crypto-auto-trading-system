"""Prompt evolution: versioned prompts with performance comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class PromptVersion:
    version: str
    template: str
    performance: float
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class PromptEvolutionEngine:
    def __init__(self) -> None:
        self.versions: dict[str, PromptVersion] = {}

    def add(self, version: str, template: str, performance: float) -> None:
        self.versions[version] = PromptVersion(version, template, performance)

    def best(self) -> PromptVersion | None:
        if not self.versions:
            return None
        return max(self.versions.values(), key=lambda p: p.performance)
