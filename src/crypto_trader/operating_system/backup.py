"""Backup and restore orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BackupResult:
    backup_id: str
    status: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class BackupOrchestrator:
    def __init__(self) -> None:
        self.backups: list[BackupResult] = []

    async def backup(self, backup_id: str) -> BackupResult:
        result = BackupResult(backup_id=backup_id, status="COMPLETED")
        self.backups.append(result)
        return result

    async def restore(self, backup_id: str) -> BackupResult:
        if not any(b.backup_id == backup_id for b in self.backups):
            return BackupResult(backup_id=backup_id, status="NOT_FOUND")
        return BackupResult(backup_id=backup_id, status="RESTORED")
