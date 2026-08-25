"""Upgrade and rollback manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class UpgradeRecord:
    version: str
    status: str
    deployed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class UpgradeManager:
    def __init__(self) -> None:
        self.records: list[UpgradeRecord] = []
        self.current = "unknown"

    def deploy(self, version: str) -> UpgradeRecord:
        record = UpgradeRecord(version=version, status="DEPLOYED")
        self.records.append(record)
        self.current = version
        return record

    def rollback(self) -> UpgradeRecord | None:
        if len(self.records) < 2:
            return None
        previous = self.records[-2]
        self.current = previous.version
        return UpgradeRecord(version=previous.version, status="ROLLED_BACK")
