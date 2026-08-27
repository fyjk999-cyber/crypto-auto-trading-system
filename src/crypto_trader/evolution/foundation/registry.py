"""Candidate registry and generation service."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.evolution.foundation.contracts import (
    Candidate,
)
from crypto_trader.evolution.foundation.policy import EvolutionMutationPolicy


class CandidateRegistry:
    def __init__(self, policy: EvolutionMutationPolicy | None = None) -> None:
        self.policy = policy or EvolutionMutationPolicy()
        self.candidates: dict[str, Candidate] = {}
        self.rejections: list[dict] = []

    def register(self, candidate: Candidate) -> tuple[bool, str]:
        ok, reason = self.policy.validate(candidate)
        if not ok:
            self.rejections.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "reason": reason,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            return False, reason
        if candidate.candidate_id in self.candidates:
            return False, "DUPLICATE"
        for existing in self.candidates.values():
            if (
                existing.target_scope == candidate.target_scope
                and existing.code_hash == candidate.code_hash
                and existing.config_hash == candidate.config_hash
                and existing.parent_version == candidate.parent_version
            ):
                return False, "EQUIVALENT"
        self.candidates[candidate.candidate_id] = candidate
        return True, "REGISTERED"

    def get(self, candidate_id: str) -> Candidate | None:
        return self.candidates.get(candidate_id)

    def list_by_status(self, status: str) -> list[Candidate]:
        return [c for c in self.candidates.values() if c.status == status]

    def list_by_parent(self, parent_version: str) -> list[Candidate]:
        return [c for c in self.candidates.values() if c.parent_version == parent_version]

    def get_lineage(self, candidate_id: str) -> list[dict]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            return []
        out = []
        for lineage_id in candidate.lineage:
            item = self.candidates.get(lineage_id)
            if item is not None:
                out.append({"candidate_id": item.candidate_id, "status": item.status})
        out.append({"candidate_id": candidate.candidate_id, "status": candidate.status})
        return out

    def mark_rejected(self, candidate_id: str, reason: str) -> None:
        candidate = self.candidates.get(candidate_id)
        if candidate is not None:
            object.__setattr__(candidate, "status", "REJECTED")
            self.rejections.append(
                {
                    "candidate_id": candidate_id,
                    "reason": reason,
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    def mark_quarantined(self, candidate_id: str) -> None:
        candidate = self.candidates.get(candidate_id)
        if candidate is not None:
            object.__setattr__(candidate, "status", "QUARANTINED")
