"""Production decision tap: the shadow sidecar's ONLY entry from real trading.

Placement contract (see the directive): the tap is invoked strictly AFTER a
ChiefTrader decision has been durably committed. It never runs before the
decision, never alters it, and never sits in an await chain that the trading loop
depends on.

Non-blocking contract:

* ``observe()`` is synchronous and does nothing but attempt a ``put_nowait`` on a
  BOUNDED queue. Queue full -> the sample is dropped and counted. There is no
  ``await`` a caller can block on, and no per-decision task is spawned.
* A single long-lived consumer drains the queue and performs persistence. One
  consumer, bounded queue — never unbounded task creation.
* Every failure is swallowed and counted. A shadow fault must never reach the
  trading loop.

Reuse note: hypothetical positions are represented with the package's EXISTING
``shadow.virtual_position.VirtualPositionBook`` rather than a second model. It is
pure in-memory (no real position, no accounting, no capacity), so reusing it
preserves isolation instead of eroding it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.shadow.candidate_store import ShadowCandidateStore
from crypto_trader.shadow.eligibility import shadow_eligibility

#: §7 bounded queue. Overflow is a normal, counted outcome — not an error.
MAX_QUEUE_DEPTH = 512

REASON_QUEUE_FULL = "SHADOW_SAMPLE_DROPPED_QUEUE_FULL"
REASON_ENQUEUE_ERROR = "SHADOW_ENQUEUE_ERROR"


def _coerce_datetime(value) -> datetime | None:
    """Accept the decision's ISO string (its real contract) or a datetime.

    ``ChiefTraderDecision.created_at`` is a STRING, so passing it through
    verbatim would raise inside persistence and be swallowed as a store error —
    silently losing every sample. Normalising here keeps that failure impossible.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


@dataclass(slots=True)
class ShadowObservation:
    """Facts read from an ALREADY-COMMITTED decision. No new evaluation."""

    decision_id: str
    symbol: str
    action: str
    reason_codes: list[str] = field(default_factory=list)
    thesis: str | None = None
    market_data_quality: str | None = None
    reference_price: Decimal | None = None
    market_regime: str | None = None
    strategy_id: str = "live_llm"
    strategy_version: str = "unknown"
    market_snapshot_id: str | None = None
    factor_snapshot_id: str | None = None
    decided_at: datetime | None = None


@dataclass(slots=True)
class ShadowTapStats:
    """Observability only (§33). Never consulted by trading code."""

    observed: int = 0
    enqueued: int = 0
    dropped_ineligible: int = 0
    dropped_queue_full: int = 0
    dropped_store_error: int = 0
    created: int = 0
    deduplicated: int = 0

    def as_dict(self) -> dict:
        return {
            "observed": self.observed,
            "enqueued": self.enqueued,
            "dropped_ineligible": self.dropped_ineligible,
            "dropped_queue_full": self.dropped_queue_full,
            "dropped_store_error": self.dropped_store_error,
            "created": self.created,
            "deduplicated": self.deduplicated,
        }


class ShadowDecisionTap:
    """Bounded, best-effort tap between committed decisions and the sidecar."""

    def __init__(
        self,
        store: ShadowCandidateStore,
        *,
        max_queue_depth: int = MAX_QUEUE_DEPTH,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.enabled = bool(enabled)
        self.max_queue_depth = max(1, int(max_queue_depth))
        self.stats = ShadowTapStats()
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self.max_queue_depth)
        self._consumer: asyncio.Task | None = None
        #: Test/observability hook: invoked for every persisted candidate.
        self.on_persisted = None

    # -------------------------------------------------------------- producer
    def observe(self, observation: ShadowObservation) -> str:
        """Synchronous, non-blocking. Returns the decision taken, for tests.

        This is the ONLY call the trading path makes, and it never awaits.
        """
        if not self.enabled:
            return "SHADOW_DISABLED"
        try:
            self.stats.observed += 1
            verdict = shadow_eligibility(
                action=observation.action,
                reason_codes=observation.reason_codes,
                thesis=observation.thesis,
                market_data_quality=observation.market_data_quality,
                reference_price=observation.reference_price,
                decision_persisted=True,
                market_regime=observation.market_regime,
            )
            if not verdict.eligible:
                self.stats.dropped_ineligible += 1
                return f"INELIGIBLE:{verdict.reason}"

            payload = {
                "symbol": observation.symbol,
                "direction_hypothesis": verdict.direction_hypothesis,
                "reference_price": str(observation.reference_price),
                "source_decision_id": observation.decision_id,
                "strategy_id": observation.strategy_id,
                "strategy_version": observation.strategy_version,
                "market_snapshot_id": observation.market_snapshot_id,
                "factor_snapshot_id": observation.factor_snapshot_id,
                "market_regime": observation.market_regime,
                "chieftrader_action": observation.action,
                "chieftrader_reason": (observation.thesis or "")[:2000],
                "created_at": _coerce_datetime(observation.decided_at),
            }
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:
                # §16/§20: dropping shadow samples is acceptable; slowing the
                # trading loop is not.
                self.stats.dropped_queue_full += 1
                return REASON_QUEUE_FULL
            self.stats.enqueued += 1
            return "ENQUEUED"
        except Exception:
            # FAIL OPEN toward real trading: never raise into the caller.
            self.stats.dropped_store_error += 1
            return REASON_ENQUEUE_ERROR

    # -------------------------------------------------------------- consumer
    async def start(self) -> None:
        """Start the single bounded consumer (idempotent)."""
        if self._consumer is None or self._consumer.done():
            self._consumer = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            consumer.cancel()
            try:
                await consumer
            except (asyncio.CancelledError, Exception):
                pass

    async def drain_once(self, *, limit: int | None = None) -> int:
        """Persist queued observations. Exposed for deterministic tests."""
        persisted = 0
        budget = self._queue.qsize() if limit is None else max(0, int(limit))
        for _ in range(budget):
            try:
                payload = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                result = await self.store.enqueue(payload)
                if result.accepted and result.deduplicated:
                    self.stats.deduplicated += 1
                elif result.accepted:
                    self.stats.created += 1
                    if self.on_persisted is not None:
                        self.on_persisted(result.candidate_id)
                else:
                    self.stats.dropped_store_error += 1
                persisted += 1
            except Exception:
                self.stats.dropped_store_error += 1
            finally:
                self._queue.task_done()
        return persisted

    async def _drain(self) -> None:
        while True:
            try:
                await asyncio.sleep(0)
                await self.drain_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats.dropped_store_error += 1
            await asyncio.sleep(0.5)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()


__all__ = [
    "MAX_QUEUE_DEPTH",
    "REASON_ENQUEUE_ERROR",
    "REASON_QUEUE_FULL",
    "ShadowDecisionTap",
    "ShadowObservation",
    "ShadowTapStats",
]
