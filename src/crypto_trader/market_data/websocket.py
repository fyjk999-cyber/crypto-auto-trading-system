"""WebSocket reconnect policy.

PORTED from Kalshi v2 runtime-safety semantics (reconnect instead of blind
resubmit; backoff; after reconnect, resync snapshots).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class WebSocketReconnectPolicy:
    max_attempts: int = 5
    base_delay: float = 0.2
    max_delay: float = 5.0
    attempts: int = 0
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    resync_required: bool = False
    history: list[dict] = field(default_factory=list)

    def on_connected(self) -> None:
        self.attempts = 0
        self.last_connected_at = datetime.now(timezone.utc)
        self.history.append({"event": "connected", "at": self.last_connected_at.isoformat()})

    def on_disconnected(self) -> None:
        self.attempts += 1
        self.last_disconnected_at = datetime.now(timezone.utc)
        self.resync_required = True
        self.history.append({"event": "disconnected", "attempt": self.attempts,
                             "at": self.last_disconnected_at.isoformat()})

    def should_reconnect(self) -> bool:
        return self.attempts <= self.max_attempts

    async def wait_backoff(self) -> None:
        if self.attempts <= 1:
            return
        delay = min(self.base_delay * (2 ** (self.attempts - 2)), self.max_delay)
        await asyncio.sleep(delay)

    def exhausted(self) -> bool:
        return self.attempts > self.max_attempts
