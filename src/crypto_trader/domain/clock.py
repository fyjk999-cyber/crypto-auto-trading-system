"""Clock abstraction.

PORTED from SilverQuant backend/app/core/clock.py.

The SilverQuant clock contract (one time source, no bare datetime.now() in
decision paths, deterministic SimClock with step()) is kept. All A-share/HK
session logic and T+1 settlement rules are intentionally removed: crypto is
24/7 and session rules belong to adapters.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence


class Clock:
    """All time-dependent logic must use Clock.now()."""

    def now(self) -> datetime:  # pragma: no cover - abstract
        raise NotImplementedError

    def utc_now(self) -> datetime:
        return self.now().astimezone(timezone.utc)


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimClock(Clock):
    """Deterministic replay/simulation clock driven by a fixed tick sequence.

    PORTED from SilverQuant SimClock; copied out then modified in this project.
    """

    def __init__(self, ticks: Sequence[datetime]) -> None:
        self._ticks = sorted(ticks)
        self._idx = -1
        self._cur: datetime | None = None
        self._prev: datetime | None = None

    def now(self) -> datetime:
        if self._cur is None:
            raise RuntimeError("SimClock has not been stepped")
        return self._cur

    def prev(self) -> datetime | None:
        return self._prev

    def step(self) -> datetime | None:
        self._prev = self._cur
        self._idx += 1
        if self._idx >= len(self._ticks):
            self._cur = None
            return None
        self._cur = self._ticks[self._idx]
        return self._cur

    def reset(self) -> None:
        self._idx = -1
        self._cur = None
        self._prev = None
