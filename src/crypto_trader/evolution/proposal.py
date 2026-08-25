"""AI improvement proposal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class EvolutionProposal:
    proposal_id: str
    title: str
    parameter_changes: dict
    rationale: str
    status: str = "PROPOSED"
    evidence: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def create_proposal(
    proposal_id: str, title: str, parameter_changes: dict, rationale: str
) -> EvolutionProposal:
    return EvolutionProposal(
        proposal_id=proposal_id,
        title=title,
        parameter_changes=parameter_changes,
        rationale=rationale,
    )
