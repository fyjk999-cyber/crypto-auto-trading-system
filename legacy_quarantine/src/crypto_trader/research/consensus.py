"""Research consensus engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResearchConsensus:
    bullish_evidence: list[str]
    bearish_evidence: list[str]
    neutral_evidence: list[str]
    confidence: float
    conclusion: str

    def to_dict(self) -> dict:
        return {
            "bullish_evidence": self.bullish_evidence,
            "bearish_evidence": self.bearish_evidence,
            "neutral_evidence": self.neutral_evidence,
            "confidence": self.confidence,
            "conclusion": self.conclusion,
        }


class ResearchConsensusEngine:
    def consensus(self, research: list[dict]) -> dict:
        bull = []
        bear = []
        neutral = []
        for r in research:
            result = r.get("result", r.get("conclusion", "NEUTRAL")).upper()
            text = r.get("conclusion", r.get("question", ""))
            if "BULL" in result or "POSITIVE" in result or "VALIDATED" in result:
                bull.append(text)
            elif "BEAR" in result or "NEGATIVE" in result or "REJECTED" in result:
                bear.append(text)
            else:
                neutral.append(text)
        total = len(bull) + len(bear) + len(neutral)
        confidence = max(0.0, min(1.0, total / 10)) if total else 0.0
        if bull and not bear:
            conclusion = "bullish tilt"
        elif bear and not bull:
            conclusion = "bearish tilt"
        elif bull and bear:
            conclusion = "mixed evidence"
        else:
            conclusion = "neutral"
        return ResearchConsensus(bull, bear, neutral, confidence, conclusion).to_dict()
