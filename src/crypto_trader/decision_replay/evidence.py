"""DecisionEvidence SSOT: decision truth, links factor snapshot refs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class DecisionEvidence:
    decision_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    strategy_id: str
    strategy_version: str
    model_version: str
    prompt_version: str
    factor_snapshot_id: str
    factor_set_version: str
    factor_profile: str
    market_data_reference: str
    analysis_evidence: dict
    decision: dict
    risk_decision: dict
    execution_intent_reference: str = ""
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "timestamp_utc": self.timestamp_utc,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "factor_snapshot_id": self.factor_snapshot_id,
            "factor_set_version": self.factor_set_version,
            "factor_profile": self.factor_profile,
            "market_data_reference": self.market_data_reference,
            "analysis_evidence": dict(self.analysis_evidence),
            "decision": dict(self.decision),
            "risk_decision": dict(self.risk_decision),
            "execution_intent_reference": self.execution_intent_reference,
            "created_at_utc": self.created_at_utc,
        }


class DecisionEvidenceStore:
    def __init__(self) -> None:
        self.evidences: dict[str, DecisionEvidence] = {}

    def store(self, evidence: DecisionEvidence) -> None:
        self.evidences[evidence.decision_id] = evidence

    def get(self, decision_id: str) -> DecisionEvidence | None:
        return self.evidences.get(decision_id)
