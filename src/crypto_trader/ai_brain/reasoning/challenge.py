"""Self challenge mechanism."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChallengeResult:
    bull_case: str
    bear_case: str
    decision_confidence: float


class SelfChallenge:
    def challenge(
        self,
        *,
        thesis: str,
        supporting: list[str],
        contradicting: list[str],
        base_confidence: float,
    ) -> ChallengeResult:
        bull = thesis + " " + " ".join(supporting[:2])
        bear = " ".join(contradicting) if contradicting else "no clear counter evidence"
        penalty = min(0.35, 0.08 * len(contradicting))
        return ChallengeResult(
            bull_case=bull,
            bear_case=bear,
            decision_confidence=round(max(0.05, base_confidence - penalty), 3),
        )
