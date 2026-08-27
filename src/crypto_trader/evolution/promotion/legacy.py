"""Promotion workflow. Cannot bypass shadow/backtest/OOS/walk-forward."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class PromotionResult:
    promoted: bool
    reason: str
    promoted_at: str = ""


class EvolutionPromoter:
    def __init__(self) -> None:
        self.promoted: dict[str, dict] = {}

    def promote(self, proposal, evidence: list[str]) -> PromotionResult:
        required = ["BACKTEST_PASS", "OOS_PASS", "WALK_FORWARD_PASS", "SHADOW_PASS"]
        if not all(stage in evidence for stage in required):
            return PromotionResult(False, f"MISSING_EVIDENCE:{','.join(required)}")
        proposal.status = "PROMOTED"
        self.promoted[proposal.proposal_id] = {
            "title": proposal.title,
            "parameter_changes": proposal.parameter_changes,
            "promoted_at": datetime.now(UTC).isoformat(),
        }
        return PromotionResult(True, "PROMOTED", datetime.now(UTC).isoformat())
