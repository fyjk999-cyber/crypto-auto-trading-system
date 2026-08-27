"""Candidate certification."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class CandidateCertification:
    candidate_id: str
    validation_run_id: str
    status: str  # PASS | FAIL | QUARANTINE
    certified_at_utc: str = None

    def __post_init__(self):
        self.certified_at_utc = self.certified_at_utc or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        return {"candidate_id": self.candidate_id,
                "validation_run_id": self.validation_run_id,
                "status": self.status, "certified_at_utc": self.certified_at_utc}


def certify(run) -> CandidateCertification:
    if run.status == "VALIDATED":
        status = "PASS"
    elif any("GUARDRAIL" in w for w in run.warnings):
        status = "QUARANTINE"
    else:
        status = "FAIL"
    return CandidateCertification(run.candidate_id, run.run_id, status)
