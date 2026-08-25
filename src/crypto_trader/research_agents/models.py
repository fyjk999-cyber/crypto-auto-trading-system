"""Research agent models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AgentReport:
    agent: str
    finding: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "finding": self.finding,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }


@dataclass
class ResearchConsensus:
    bullish_evidence: list[str]
    bearish_evidence: list[str]
    uncertainty: list[str]
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "bullish_evidence": self.bullish_evidence,
            "bearish_evidence": self.bearish_evidence,
            "uncertainty": self.uncertainty,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }
