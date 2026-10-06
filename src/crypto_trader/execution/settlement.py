"""Account-scoped settlement fence. Synchronous state, never callback locks.

All methods run on the engine event loop. A generation changes before external
account mutation and after durable local completion. Faults stay fail-closed.
"""

from __future__ import annotations

import math
import time
from collections import deque
from datetime import UTC, datetime


class SettlementCoordinator:
    def __init__(self, *, stale_seconds=120.0, clock=time.monotonic, journal=None):
        self.stale_seconds = float(stale_seconds)
        if (
            isinstance(stale_seconds, bool)
            or not math.isfinite(self.stale_seconds)
            or self.stale_seconds <= 0
        ):
            raise ValueError("settlement stale deadline must be finite and positive")
        self.clock = clock
        self.generation = 0
        self.active: dict[str, dict] = {}
        self.faults: dict[str, str] = {}
        self.events = deque(maxlen=128)
        self.journal = journal
        self.batches: dict[str, dict] = {}
        self.parent_by_fill: dict[str, str] = {}

    def _event(self, event, token):
        self.events.append(
            {
                "event": event,
                "token": token,
                "generation": self.generation,
                "at": datetime.now(UTC).isoformat(),
            }
        )

    def begin(self, token, source="EXTERNAL_FILL", parent=None):
        if token not in self.active:
            self.generation += 1
            self.active[token] = {
                "started": self.clock(),
                "source": source,
                "started_at": datetime.now(UTC).isoformat(),
            }
            self._event("SETTLEMENT_BEGIN", token)
        if parent is not None:
            self.batches[parent]["children"].add(token)
            self.parent_by_fill[token] = parent

    async def begin_batch(self, token, order_id):
        self.begin(token, "PAPER_ACCOUNT_MUTATION")
        self.batches[token] = {"children": set(), "sealed": False}
        try:
            if self.journal is None:
                raise RuntimeError("external settlement journal not wired")
            # Durable UNKNOWN marker BEFORE external account mutation. A crash
            # cannot turn loss of volatile tokens into a falsely healthy start.
            await self.journal("SETTLEMENT_EXTERNAL_BEGIN", token, order_id)
        except BaseException as exc:
            self.fault(token, type(exc).__name__)
            raise

    async def seal_batch(self, token):
        self.batches[token]["sealed"] = True
        await self._finish_batch(token)

    async def complete_local(self, token):
        self.complete(token)
        parent = self.parent_by_fill.get(token)
        if parent is not None:
            await self._finish_batch(parent)

    async def _finish_batch(self, token):
        batch = self.batches[token]
        if not batch["sealed"] or token in self.faults:
            return
        if any(child in self.active or child in self.faults for child in batch["children"]):
            return
        try:
            await self.journal("SETTLEMENT_EXTERNAL_COMPLETE", token, None)
        except BaseException as exc:
            self.fault(token, type(exc).__name__)
            raise
        self.complete(token)
        for child in batch["children"]:
            self.parent_by_fill.pop(child, None)
        del self.batches[token]

    def complete(self, token):
        # A duplicate or later callback must not silently clear a retained fault.
        if token in self.active and token not in self.faults:
            self.generation += 1
            del self.active[token]
            self._event("SETTLEMENT_COMPLETE", token)

    def fault(self, token, reason):
        self.begin(token, "FAULT")
        if token not in self.faults:
            self.generation += 1
            self.faults[token] = reason
            self._event("SETTLEMENT_FAULT", token)

    def snapshot(self):
        now = self.clock()
        age = max((now - x["started"] for x in self.active.values()), default=0.0)
        state = (
            "SETTLEMENT_FAULT"
            if self.faults
            else "SETTLEMENT_STALE"
            if age > self.stale_seconds
            else "PENDING_SETTLEMENT"
            if self.active
            else "COHERENT"
        )
        return {
            "state": state,
            "generation": self.generation,
            "active_count": len(self.active),
            "oldest_age_seconds": age,
            "stale_threshold_seconds": self.stale_seconds,
            "faults": dict(self.faults),
            "active_tokens": {
                k: {"source": v["source"], "started_at": v["started_at"]}
                for k, v in list(self.active.items())[:128]
            },
            "events": list(self.events),
        }

    def coherent(self, generation):
        return self.generation == generation and self.snapshot()["state"] == "COHERENT"
