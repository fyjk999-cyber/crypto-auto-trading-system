"""LLM offline mode runtime guard (Low-Risk V2 Phase 4, SPEC OFFLINE RULE).

Only when DeepSeek+retry AND GLM+retry both fail does the system enter
``LLM_OFFLINE_MODE``. While offline:

  * OPEN / ADD / HEDGE / REVERSE / RE-ENTRY are forbidden;
  * pending new-risk orders are identified for cancellation + reconciliation;
  * only HOLD / REDUCE / CLOSE / protective exits remain allowed;
  * recovery uses five-minute probe windows (5m, 10m, 15m, ...), and a recovered
    provider returns to NORMAL immediately after factual reconciliation is
    coherent.

This module is deterministic book-keeping; it never submits an order and does
not replace the CoreLLMRouter, RecoveryService or ReconciliationService.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

NEW_RISK_LIFECYCLE_ACTIONS = {"OPEN", "ENTRY", "ADD", "HEDGE", "REVERSE", "RE_ENTRY", "REENTRY"}
PROTECTIVE_LIFECYCLE_ACTIONS = {
    "REDUCE",
    "EXIT",
    "CLOSE",
    "BASE_EXIT",
    "FAST_PROFIT_PROTECTION",
    "RISK_HARD_EXIT",
    "OFFLINE_HARD_EXIT",
}
PROTECTIVE_AUTHORITIES = {
    "ACTIVE_BASE_EXIT",
    "FAST_PROFIT_PROTECTION",
    "RISK_HARD_EXIT",
    "OFFLINE_HARD_EXIT",
}


@dataclass(slots=True)
class OfflineSnapshot:
    offline: bool
    windows: int
    entered_at: str | None
    next_probe_at: str | None
    reason: str | None
    recovering: bool = False
    last_reconcile_ok: bool | None = None

    def as_dict(self) -> dict:
        return {
            "offline": self.offline,
            "windows": self.windows,
            "entered_at": self.entered_at,
            "next_probe_at": self.next_probe_at,
            "reason": self.reason,
            "recovering": self.recovering,
            "last_reconcile_ok": self.last_reconcile_ok,
        }


@dataclass
class OfflineMode:
    window_seconds: float = 300.0
    entered_at: datetime | None = None
    next_probe_at: datetime | None = None
    windows: int = 0
    reason: str | None = None
    recovering: bool = False
    last_reconcile_ok: bool | None = None
    events: list[dict] = field(default_factory=list)

    @property
    def is_offline(self) -> bool:
        return self.entered_at is not None

    def allows_new_risk(self) -> bool:
        return not self.is_offline

    # ------------------------------------------------------------------ enter
    def enter(self, reason: str, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        if self.is_offline:
            return False
        self.entered_at = moment
        self.next_probe_at = moment + timedelta(seconds=self.window_seconds)
        self.windows = 1
        self.reason = reason
        self.recovering = False
        self._event("LLM_OFFLINE_MODE", moment, reason)
        return True

    # ----------------------------------------------------------- probe/recover
    def probe_due(self, *, now: datetime | None = None) -> bool:
        if not self.is_offline or self.next_probe_at is None:
            return False
        return (now or datetime.now(UTC)) >= self.next_probe_at

    def probe_failed(self, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        self.next_probe_at = moment + timedelta(seconds=self.window_seconds)
        self.windows += 1
        self._event("OFFLINE_PROBE_FAILED", moment, self.reason)

    def probe_not_due(self, *, now: datetime | None = None) -> None:
        self._event("OFFLINE_WAIT_NEXT_WINDOW", now or datetime.now(UTC), self.reason)

    def begin_recovery(self, *, now: datetime | None = None) -> None:
        self.recovering = True
        self._event("OFFLINE_RECOVERY_STARTED", now or datetime.now(UTC), self.reason)

    def complete_recovery(self, *, reconciled: bool, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        self.last_reconcile_ok = reconciled
        if not reconciled:
            # Not coherent yet: stay offline and schedule the next window.
            self.recovering = False
            self.probe_failed(now=moment)
            return False
        self._event("OFFLINE_RECOVERED", moment, self.reason)
        self.entered_at = None
        self.next_probe_at = None
        self.windows = 0
        self.reason = None
        self.recovering = False
        return True

    # ------------------------------------------------------------ order rules
    @staticmethod
    def order_class(metadata: dict | None, strategy_id: str | None = None) -> str:
        meta = metadata or {}
        action = str(meta.get("lifecycle_action") or "").upper()
        authority = str(meta.get("exit_authority") or "")
        if meta.get("reduce_only") is True or action in PROTECTIVE_LIFECYCLE_ACTIONS:
            return "PROTECTIVE"
        if authority in PROTECTIVE_AUTHORITIES:
            return "PROTECTIVE"
        if action in NEW_RISK_LIFECYCLE_ACTIONS or strategy_id == "live_llm":
            return "NEW_RISK"
        return "OTHER"

    def blocks_new_risk(self, metadata: dict | None, strategy_id: str | None = None) -> bool:
        return self.is_offline and self.order_class(metadata, strategy_id) == "NEW_RISK"

    def pending_new_risk_orders(self, orders: list) -> list:
        """Filter open orders to the pending new-risk ones that must be cancelled."""
        out = []
        for order in orders:
            metadata = getattr(order, "metadata", None) or {}
            strategy_id = getattr(order, "strategy_id", None)
            if self.order_class(metadata, strategy_id) == "NEW_RISK":
                out.append(order)
        return out

    def snapshot(self) -> dict:
        return OfflineSnapshot(
            offline=self.is_offline,
            windows=self.windows,
            entered_at=self.entered_at.isoformat() if self.entered_at else None,
            next_probe_at=self.next_probe_at.isoformat() if self.next_probe_at else None,
            reason=self.reason,
            recovering=self.recovering,
            last_reconcile_ok=self.last_reconcile_ok,
        ).as_dict()

    def _event(self, event: str, moment: datetime, reason: str | None) -> None:
        self.events.append(
            {"event": event, "at": moment.isoformat(), "reason": reason, "windows": self.windows}
        )
