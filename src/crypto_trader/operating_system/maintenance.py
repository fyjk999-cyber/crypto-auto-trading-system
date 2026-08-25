"""Maintenance window management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class MaintenanceWindow:
    starts_at: str
    ends_at: str
    reason: str
    status: str = "SCHEDULED"


class MaintenanceManager:
    def __init__(self) -> None:
        self.windows: list[MaintenanceWindow] = []

    def schedule(self, starts_at: str, ends_at: str, reason: str) -> MaintenanceWindow:
        window = MaintenanceWindow(starts_at=starts_at, ends_at=ends_at, reason=reason)
        self.windows.append(window)
        return window

    def active(self, now: datetime | None = None) -> list[MaintenanceWindow]:
        now = now or datetime.now(UTC)
        return [w for w in self.windows if w.starts_at <= now.isoformat() <= w.ends_at]
