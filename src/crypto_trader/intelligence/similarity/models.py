"""Similarity models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimilarCase:
    case_id: str
    similarity: float
    outcome: str
    regime: str

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "similarity": self.similarity,
            "outcome": self.outcome,
            "regime": self.regime,
        }
