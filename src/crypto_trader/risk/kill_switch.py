from __future__ import annotations

from datetime import datetime, timezone


class KillSwitch:
    """Global trading-system kill switch. ON => no new orders, always."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled
        self._reason: str | None = None
        self._engaged_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def reason(self) -> str | None:
        return self._reason

    def engage(self, reason: str) -> None:
        self._enabled = True
        self._reason = reason
        self._engaged_at = datetime.now(timezone.utc)

    def disengage(self, reason: str | None = None) -> None:
        self._enabled = False
        self._reason = reason

    def snapshot(self) -> dict:
        return {
            "enabled": self._enabled,
            "reason": self._reason,
            "engaged_at": self._engaged_at.isoformat() if self._engaged_at else None,
        }
