"""Canonical position lifecycle tracking (directive P2-1, §8-§15).

Single shared source of truth for POSITION EPISODE transitions inside one
runtime process. It exists to make the exit -> re-entry boundary explicit:

* EXIT_UNBLOCKED: exits are NEVER gated by this tracker. Nothing here may
  delay, veto, or reshape a reduce-only / closing order.
* REVERSAL_COOLDOWN: a NEW ENTRY for a symbol whose position episode was
  just closed must wait until the lifecycle is finalized. This is lifecycle
  consistency / duplicate-noise protection (§10), NOT a Quant Gate: it never
  judges direction, fit, confidence, or thesis. ChiefTrader AI authority,
  RiskEngine, and ExecutionAuthority are unchanged.
* POSITION VERSION: monotonically bumped on every position transition so an
  entry SignalIntent can carry the position state it was decided against
  (§12 signal precondition). The engine rejects intents whose expected
  version no longer matches reality (REJECT_STALE_SIGNAL) instead of blindly
  executing an old decision across a lifecycle boundary (§11).

Keys are CANONICAL internal symbols scoped by market type
(``<MARKET_TYPE>|<SYMBOL>``), e.g. ``SPOT|TRXUSDT`` and ``PERPETUAL|TRXUSDT_PERP``
are distinct scopes on purpose (different instruments); the same instrument
can never appear under two string variants because every caller passes the
canonical internal symbol used by orders/fills.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def lifecycle_key(symbol: str, market_type) -> str:
    """Canonical lifecycle key: market type scopes the instrument identity."""
    market = getattr(market_type, "value", str(market_type))
    return f"{str(market).upper()}|{str(symbol).upper()}"


@dataclass
class LifecycleEvent:
    at_unix: float
    kind: str  # OPENED / CLOSED / CHANGED
    symbol: str
    market_type: str


@dataclass
class PositionLifecycleTracker:
    """In-memory, single-process record of position episode transitions.

    Restarts intentionally reset it: a restart is a controlled lifecycle
    boundary (recovery/reconciliation re-canonicalizes positions), and the
    reversal cooldown is a short-horizon duplicate-noise fence, not durable
    risk state (RiskEngine remains the only durable safety authority).
    """

    reversal_cooldown_seconds: float = 240.0
    max_events: int = 512
    _version: dict[str, int] = field(default_factory=dict)
    _last_exit_settled_at: dict[str, float] = field(default_factory=dict)
    _last_exit_symbol_event: dict[str, LifecycleEvent] = field(
        default_factory=dict
    )
    _events: list[LifecycleEvent] = field(default_factory=list)

    # ------------------------------------------------------------ ingestion
    def on_position_opened(self, symbol: str, market_type) -> None:
        self._record(symbol, market_type, "OPENED")

    def on_position_closed(self, symbol: str, market_type) -> None:
        """A position episode completed (flat reached). Starts the reversal
        fence. NEVER called for exits that were rejected/held: those never
        changed position state, so no fence may start (no cooldown
        corruption from failed exits)."""
        key = lifecycle_key(symbol, market_type)
        self._last_exit_settled_at[key] = time.monotonic()
        self._record(symbol, market_type, "CLOSED")

    def on_position_changed(self, symbol: str, market_type) -> None:
        """Add/reduce inside an open episode: version bump only."""
        self._record(symbol, market_type, "CHANGED")

    def _record(self, symbol: str, market_type, kind: str) -> None:
        key = lifecycle_key(symbol, market_type)
        self._version[key] = self._version.get(key, 0) + 1
        event = LifecycleEvent(
            at_unix=time.time(), kind=kind, symbol=str(symbol).upper(),
            market_type=str(getattr(market_type, "value", market_type)).upper(),
        )
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]
        if kind == "CLOSED":
            self._last_exit_symbol_event[key] = event

    # ------------------------------------------------------------- queries
    def position_version(self, symbol: str, market_type) -> int:
        return self._version.get(lifecycle_key(symbol, market_type), 0)

    def seconds_since_exit(self, symbol: str, market_type) -> float | None:
        """Seconds since the last COMPLETED position close, or None when no
        close was ever observed in this process (never blocks in that case:
        missing state must not invent a fence)."""
        settled = self._last_exit_settled_at.get(lifecycle_key(symbol, market_type))
        if settled is None:
            return None
        return max(0.0, time.monotonic() - settled)

    def reversal_blocked(self, symbol: str, market_type) -> bool:
        """True only inside the reversal cooldown window after a completed
        close of the SAME instrument. Exits are never blocked by this call."""
        since = self.seconds_since_exit(symbol, market_type)
        if since is None:
            return False
        return since < max(0.0, float(self.reversal_cooldown_seconds))

    # ---------------------------------------------------------- snapshot
    def snapshot(self, symbols: list[tuple[str, object]] | None = None) -> dict:
        """Bounded observability snapshot for /health and monitoring (§74)."""
        if symbols is None:
            keys = set(self._version) | set(self._last_exit_settled_at)
        else:
            keys = {lifecycle_key(s, m) for s, m in symbols}
        out: dict[str, dict] = {}
        now_mono = time.monotonic()
        for key in sorted(keys):
            out[key] = {
                "position_version": self._version.get(key, 0),
                "seconds_since_exit": (
                    round(now_mono - settled, 3)
                    if (settled := self._last_exit_settled_at.get(key)) is not None
                    else None
                ),
                "reversal_blocked": self.reversal_blocked(*self._split_key(key)),
            }
        return out

    @staticmethod
    def _split_key(key: str) -> tuple[str, str]:
        market, _, symbol = key.partition("|")
        return symbol, market
