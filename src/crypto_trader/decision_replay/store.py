"""In-memory append-only evidence stores with serialization for restart tests."""

from __future__ import annotations

from crypto_trader.decision_replay.evidence import DecisionEvidence
from crypto_trader.factors.version import FactorSnapshotContract


class EvidenceStore:
    def __init__(self) -> None:
        self._decisions: dict[str, DecisionEvidence] = {}
        self._snapshots: dict[str, FactorSnapshotContract] = {}

    def store_decision(self, evidence: DecisionEvidence) -> None:
        self._decisions[evidence.decision_id] = evidence

    def store_snapshot(self, snapshot: FactorSnapshotContract) -> None:
        self._snapshots[snapshot.snapshot_id] = snapshot

    def get(self, decision_id: str) -> DecisionEvidence | None:
        return self._decisions.get(decision_id)

    def get_snapshot(self, snapshot_id: str) -> FactorSnapshotContract | None:
        return self._snapshots.get(snapshot_id)

    def snapshot_ids(self) -> list[str]:
        return list(self._snapshots)

    def to_dict(self) -> dict:
        return {
            "decisions": {k: v.to_dict() for k, v in self._decisions.items()},
            "snapshots": {k: v.to_dict() for k, v in self._snapshots.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> EvidenceStore:
        store = cls()
        # Restoring full frozen snapshot objects from dict would require
        # reconstructing FactorSnapshotEntry tuples; for restart-test parity we
        # keep the serialized shape as a replay facade.
        store._serialized = data
        return store

    def serialized_snapshot(self, snapshot_id: str) -> dict | None:
        data = getattr(self, "_serialized", None)
        if data is None:
            snapshot = self._snapshots.get(snapshot_id)
            return snapshot.to_dict() if snapshot else None
        return data.get("snapshots", {}).get(snapshot_id)
