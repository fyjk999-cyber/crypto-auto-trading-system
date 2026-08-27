"""Historical replay. Uses stored evidence, never recomputes latest factors."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReplayResult:
    decision_id: str
    information_available_at: str
    factor_snapshot: dict | None
    decision_evidence: dict | None
    future_leak: bool = False
    warnings: list = field(default_factory=list)


class HistoricalReplayEngine:
    def __init__(self) -> None:
        self.evidence_store = None
        self.snapshot_store = None

    def wire(self, *, evidence_store, snapshot_store) -> None:
        self.evidence_store = evidence_store
        self.snapshot_store = snapshot_store

    def replay(self, decision_id: str) -> ReplayResult:
        evidence = self.evidence_store.get(decision_id)
        if evidence is None:
            return ReplayResult(decision_id, "", None, None, warnings=["MISSING_EVIDENCE"])
        snapshot_id = evidence.factor_snapshot_id
        snapshot = self.snapshot_store.get_snapshot(snapshot_id)
        return ReplayResult(
            decision_id=decision_id,
            information_available_at=evidence.timestamp_utc,
            factor_snapshot=snapshot.to_dict() if snapshot else None,
            decision_evidence=evidence.to_dict(),
        )
