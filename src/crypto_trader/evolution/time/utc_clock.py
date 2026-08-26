"""UTC clock abstraction for evolution scheduling.

Production implementation returns timezone-aware UTC. Tests use FakeUtcClock
and MUST NOT depend on host timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FakeUtcClock:
    current: datetime

    def __init__(self, current: datetime | None = None) -> None:
        self.current = current or datetime(2026, 8, 26, 0, 5, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> datetime:
        self.current = self.current + __import__("datetime").timedelta(**kwargs)
        return self.current
