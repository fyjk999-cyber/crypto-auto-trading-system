"""Decision snapshot for replay and counterfactual analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class DecisionSnapshot:
    snapshot_id: str
    market_data: dict
    quant_evidence: dict
    knowledge: dict
    memory: dict
    coin_profile: dict
    prompt_version: str
    llm_response: dict
    risk_decision: dict
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def replay_ready(self) -> bool:
        return bool(self.market_data and self.llm_response and self.risk_decision)
