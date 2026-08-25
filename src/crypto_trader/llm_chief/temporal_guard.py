"""TemporalDataGuard: block future-data leakage at decision timestamp T."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class TemporalGuardResult:
    allowed: bool
    reason: str
    blocked_objects: list[str] = field(default_factory=list)


class TemporalDataGuard:
    def __init__(self, decision_timestamp: datetime) -> None:
        if decision_timestamp.tzinfo is None:
            decision_timestamp = decision_timestamp.replace(tzinfo=UTC)
        self.t = decision_timestamp

    def validate(self, objects: list[dict]) -> TemporalGuardResult:
        blocked = []
        for obj in objects:
            ts = obj.get("timestamp")
            if ts is None:
                continue
            try:
                parsed = datetime.fromisoformat(ts)
            except Exception:
                blocked.append(obj.get("id", "unknown"))
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if parsed > self.t:
                blocked.append(obj.get("id", "unknown"))
        if blocked:
            return TemporalGuardResult(False, "FUTURE_DATA_LEAKAGE", blocked)
        return TemporalGuardResult(True, "OK", [])
