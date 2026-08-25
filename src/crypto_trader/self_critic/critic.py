"""Self critic agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SelfCriticReport:
    episode_id: str
    correct_decisions: list[str]
    mistakes: list[str]
    future_adjustment: str
    confidence_adjustment_pct: float


class SelfCriticAgent:
    def review(
        self, episode_id: str, *, was_win: bool, ignored_btc_divergence: bool = False
    ) -> SelfCriticReport:
        correct = ["trend call"] if was_win else []
        mistakes = []
        if ignored_btc_divergence:
            mistakes.append("ignored BTC divergence")
        adjustment = -0.15 if mistakes else 0.0
        return SelfCriticReport(
            episode_id=episode_id,
            correct_decisions=correct,
            mistakes=mistakes,
            future_adjustment="reduce confidence 15%" if mistakes else "maintain confidence",
            confidence_adjustment_pct=adjustment,
        )
