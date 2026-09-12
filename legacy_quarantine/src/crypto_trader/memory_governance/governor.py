"""Memory quality governance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExperienceQuality:
    score: float


class MemoryGovernor:
    def score(
        self,
        *,
        sample_size: int,
        repeatability: float,
        regime_match: float,
        confidence: float,
        outcome_quality: float,
    ) -> ExperienceQuality:
        size_factor = min(1.0, sample_size / 100)
        score = (
            0.3 * size_factor
            + 0.2 * repeatability
            + 0.2 * regime_match
            + 0.15 * confidence
            + 0.15 * outcome_quality
        )
        return ExperienceQuality(round(score, 3))
