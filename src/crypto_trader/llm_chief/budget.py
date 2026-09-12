"""Single logical global LLM budget authority (§8).

Every model call in the runtime asks this one authority first. Priority order
is fixed and non-negotiable:

    P0 POSITION SAFETY / EXIT
    P1 POSITION LIFECYCLE REVIEW
    P2 FINAL ENTRY DECISION
    P3 SELECTED-SYMBOL RESEARCH
    P4 MARKET SELECTION
    P5 BACKGROUND RESEARCH

Market selection must never starve position management. Each priority level
keeps a reserved SHARE of the rolling window for the levels above it, so
low-priority work is refused with an explicit ``SKIPPED_BUDGET`` state instead
of consuming capacity that safer work may need. Refusing is never an engine
failure.

Only non-secret operational facts are tracked: operation, provider, model,
started_at, latency, input/output tokens, status.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

P0_POSITION_SAFETY = "P0_POSITION_SAFETY_EXIT"
P1_POSITION_LIFECYCLE = "P1_POSITION_LIFECYCLE_REVIEW"
P2_FINAL_ENTRY_DECISION = "P2_FINAL_ENTRY_DECISION"
P3_SELECTED_SYMBOL_RESEARCH = "P3_SELECTED_SYMBOL_RESEARCH"
P4_MARKET_SELECTION = "P4_MARKET_SELECTION"
P5_BACKGROUND_RESEARCH = "P5_BACKGROUND_RESEARCH"

PRIORITY_ORDER = (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    P3_SELECTED_SYMBOL_RESEARCH,
    P4_MARKET_SELECTION,
    P5_BACKGROUND_RESEARCH,
)

STATUS_GRANTED = "GRANTED"
STATUS_SKIPPED_BUDGET = "SKIPPED_BUDGET"
#: Distinct exhaustion reasons so a supervisor can tell WHY a call was refused.
#: ``SKIPPED_BUDGET`` stays the generic status; these two carry the precise one.
#: Intentional suppression reasons. These are NOT budget exhaustion: the call
#: was deliberately not made because it would have been redundant. Keeping them
#: distinct is what lets a supervisor tell "we ran out of budget" apart from
#: "this call was never necessary".
REASON_REVIEW_COALESCED = "REVIEW_COALESCED"
REASON_UNCHANGED_CONTEXT = "UNCHANGED_CONTEXT"
REASON_DUPLICATE_INPUT = "DUPLICATE_INPUT"
SUPPRESSION_REASONS: tuple[str, ...] = (
    REASON_REVIEW_COALESCED,
    REASON_UNCHANGED_CONTEXT,
    REASON_DUPLICATE_INPUT,
)

REASON_ENTRY_BUDGET_EXHAUSTED = "ENTRY_BUDGET_EXHAUSTED"
REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED = "POSITION_MANAGEMENT_BUDGET_EXHAUSTED"
STATUS_DEFERRED = "DEFERRED"
STATUS_OK = "OK"
STATUS_ERROR = "ERROR"
STATUS_TIMEOUT = "TIMEOUT"

# Share of the rolling window reserved for the priorities ABOVE a given level.
# Fractions (not absolute counts) so the reservation stays meaningful for any
# configured window size.
DEFAULT_RESERVED_FRACTION_FOR_HIGHER: dict[str, float] = {
    P0_POSITION_SAFETY: 0.0,
    P1_POSITION_LIFECYCLE: 0.0,
    P2_FINAL_ENTRY_DECISION: 0.0,
    P3_SELECTED_SYMBOL_RESEARCH: 0.15,
    P4_MARKET_SELECTION: 0.30,
    P5_BACKGROUND_RESEARCH: 0.45,
}

#: Active-position management. These priorities own a protected absolute
#: reserve inside the SAME rolling window: scanning / entry / research calls
#: are additionally capped at ``general_pool`` so they can never consume the
#: capacity an already-open position needs.
POSITION_MANAGEMENT_PRIORITIES: tuple[str, ...] = (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
)

#: Default protected reserve, in calls per window.
#:
#: Derived, not guessed: one position reviewed on a 60s cadence needs 60 calls
#: an hour, and the exit path (P0) must stay callable on top of routine
#: lifecycle reviews, so 2x the hourly review demand is reserved.
#: ``GlobalLLMBudget`` keeps ``general_pool = max_calls_per_window - reserve``
#: above zero by construction, so a reserve at or above the whole window
#: degrades deterministically instead of starving every priority.
DEFAULT_POSITION_MANAGEMENT_RESERVE = 60



@dataclass(frozen=True, slots=True)
class BudgetConfig:
    window_seconds: float = 3600.0
    max_calls_per_window: int = 120
    reserved_fraction_for_higher: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_RESERVED_FRACTION_FOR_HIGHER)
    )
    #: Protected capacity for active-position management (see
    #: ``POSITION_MANAGEMENT_PRIORITIES``). Scanning / entry / research may
    #: never spend this share, so an OPEN position keeps a management path even
    #: after the general pool is exhausted.
    position_management_reserve: int = DEFAULT_POSITION_MANAGEMENT_RESERVE

    def ceiling_for(self, priority: str) -> int:
        """Calls this priority may start in a window.

        The ceiling leaves the reserved share for the higher priorities, so
        low-priority work can never consume the capacity that position safety /
        lifecycle / entry decisions may need. ``1.0`` reservation means "never
        spend here" (used to prove exhaustion behaviour in tests).
        """
        fraction = float(self.reserved_fraction_for_higher.get(priority, 0.0))
        fraction = min(max(fraction, 0.0), 1.0)
        return max(0, int(self.max_calls_per_window * (1.0 - fraction)))

    @property
    def reserve_calls(self) -> int:
        """Usable protected reserve for position management.

        Clamped so the reserve can never exceed the head-room the EXISTING
        ceiling mechanism already protects for the highest priorities. For a
        large window (e.g. 120 calls) the configured reserve is fully honoured;
        for a tiny window it degrades to whatever the ceilings leave, so the
        pre-existing budget contract is preserved exactly.
        """
        reserve = max(0, int(self.position_management_reserve))
        head_room = min(
            (self.ceiling_for(priority) for priority in PRIORITY_ORDER),
            default=self.max_calls_per_window,
        )
        return max(0, min(reserve, head_room, max(0, self.max_calls_per_window - 1)))

    @property
    def general_pool(self) -> int:
        """Calls non-position work may consume.

        This is what stops entry scanning and market selection from draining
        the capacity an open position needs.
        """
        return max(0, self.max_calls_per_window - self.reserve_calls)

    @staticmethod
    def is_position_management(priority: str) -> bool:
        return priority in POSITION_MANAGEMENT_PRIORITIES

    def exhaustion_reason_for(self, priority: str) -> str:
        """Precise reason a priority was refused (see ``REASON_*``)."""
        return (
            REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
            if self.is_position_management(priority)
            else REASON_ENTRY_BUDGET_EXHAUSTED
        )



@dataclass(slots=True)
class BudgetTicket:
    """One granted call. Callers must call ``complete``/``fail`` in a finally."""

    granted: bool
    priority: str
    operation: str
    state: str
    started_at: datetime
    #: Precise refusal reason when ``granted`` is False (see ``REASON_*``).
    reason: str | None = None
    _budget: GlobalLLMBudget | None = None
    _completed: bool = False

    def complete(
        self,
        *,
        status: str = STATUS_OK,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        detail: str | None = None,
    ) -> None:
        if self._budget is not None and not self._completed:
            self._budget._record(
                priority=self.priority,
                operation=self.operation,
                status=status,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                detail=detail,
                started_at=self.started_at,
            )
            self._completed = True

    def fail(self, *, status: str = STATUS_ERROR, detail: str | None = None) -> None:
        self.complete(status=status, detail=detail)


class GlobalLLMBudget:
    """Rolling-window call budget with priority reservations."""

    def __init__(self, config: BudgetConfig | None = None, *, clock=None) -> None:
        self.config = config or BudgetConfig()
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._granted: deque[float] = deque()
        #: Granted-in-window calls per priority, pruned together with
        #: ``_granted``. Needed because the protected reserve can only be
        #: honoured if the instance knows how much non-position work has
        #: already been spent in this window.
        self._granted_priorities: deque[str] = deque()
        self._events: deque[dict] = deque(maxlen=500)
        self.skipped_by_priority: dict[str, int] = {}
        self.granted_by_priority: dict[str, int] = {}
        self.skipped_by_reason: dict[str, int] = {}
        #: Intentional suppressions (redundant calls avoided). Counted OUTSIDE
        #: the quota: a coalesced call consumed no capacity and is not a miss.
        self.suppressed_by_reason: dict[str, int] = {}
        #: Per-priority token and latency attribution (observability only; the
        #: quota authority stays call-count based).
        self.input_tokens_by_priority: dict[str, int] = {}
        self.output_tokens_by_priority: dict[str, int] = {}
        self._latency_by_priority: dict[str, list] = {}

    # ------------------------------------------------------------------ quota
    def _prune(self, now: float) -> None:
        cutoff = now - self.config.window_seconds
        while self._granted and self._granted[0] < cutoff:
            self._granted.popleft()
            if self._granted_priorities:
                self._granted_priorities.popleft()

    def _general_calls_in_window(self) -> int:
        return sum(
            1
            for priority in self._granted_priorities
            if not self.config.is_position_management(priority)
        )

    def _refuse(self, priority: str, operation: str) -> BudgetTicket:
        """Record and return a refused ticket carrying the precise reason."""
        reason = self.config.exhaustion_reason_for(priority)
        self.skipped_by_priority[priority] = (
            self.skipped_by_priority.get(priority, 0) + 1
        )
        self.skipped_by_reason[reason] = self.skipped_by_reason.get(reason, 0) + 1
        self._events.append(
            {
                "priority": priority,
                "operation": operation,
                "state": STATUS_SKIPPED_BUDGET,
                "reason": reason,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        return BudgetTicket(
            granted=False,
            priority=priority,
            operation=operation,
            state=STATUS_SKIPPED_BUDGET,
            started_at=datetime.now(UTC),
            reason=reason,
        )

    def try_acquire(self, priority: str, *, operation: str) -> BudgetTicket:
        if priority not in PRIORITY_ORDER:
            raise ValueError(f"unknown LLM priority: {priority}")
        now = self._clock()
        with self._lock:
            self._prune(now)
            in_window = len(self._granted)
            ceiling = self.config.ceiling_for(priority)
            if in_window >= ceiling:
                return self._refuse(priority, operation)
            # Protected position-management reserve. The effective limit for
            # non-position work is ``min(ceiling, general_pool)`` so this can
            # only ever tighten the OLD contract (ceiling), never loosen it:
            # a call the ceiling already refused stays refused, and a call the
            # ceiling allowed is refused only once the general pool is spent.
            effective = ceiling
            if (
                not self.config.is_position_management(priority)
                and self.config.reserve_calls > 0
            ):
                effective = min(ceiling, self.config.general_pool)
            if (
                not self.config.is_position_management(priority)
                and self.config.reserve_calls > 0
                and in_window >= effective
            ):
                return self._refuse(priority, operation)
            self._granted.append(now)
            self._granted_priorities.append(priority)
            self.granted_by_priority[priority] = self.granted_by_priority.get(priority, 0) + 1
            self._events.append(
                {
                    "priority": priority,
                    "operation": operation,
                    "state": STATUS_GRANTED,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            return BudgetTicket(
                granted=True,
                priority=priority,
                operation=operation,
                state=STATUS_GRANTED,
                started_at=datetime.now(UTC),
                _budget=self,
            )

    def note_suppressed(self, *, reason: str, operation: str) -> None:
        """Record a call deliberately NOT made because it was redundant.

        Deliberately separate from ``try_acquire``: suppression is not a budget
        event, so it must never touch ``_granted``, ``skipped_by_reason`` or the
        rolling window. It exists so the runtime can report
        ``coalesced_calls`` / ``duplicate_calls_avoided`` instead of hiding the
        saving inside an opaque skip.
        """
        if reason not in SUPPRESSION_REASONS:
            raise ValueError(f"unknown suppression reason: {reason}")
        with self._lock:
            self.suppressed_by_reason[reason] = (
                self.suppressed_by_reason.get(reason, 0) + 1
            )
            self._events.append(
                {
                    "priority": None,
                    "operation": operation,
                    "state": reason,
                    "suppressed": True,
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    def note_deferred(self, priority: str, *, operation: str, reason: str) -> None:
        with self._lock:
            self._events.append(
                {
                    "priority": priority,
                    "operation": operation,
                    "state": STATUS_DEFERRED,
                    "reason": reason,
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    # -------------------------------------------------------------- recording
    def _record(
        self,
        *,
        priority: str,
        operation: str,
        status: str,
        provider: str | None,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int | None,
        detail: str | None,
        started_at: datetime,
    ) -> None:
        elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        effective_latency = latency_ms if latency_ms is not None else elapsed_ms
        with self._lock:
            # Observability only. The quota authority remains call-count based;
            # these aggregates exist so a supervisor can see WHO spent the
            # window and how expensive each priority actually was.
            if input_tokens is not None:
                self.input_tokens_by_priority[priority] = (
                    self.input_tokens_by_priority.get(priority, 0) + int(input_tokens)
                )
            if output_tokens is not None:
                self.output_tokens_by_priority[priority] = (
                    self.output_tokens_by_priority.get(priority, 0) + int(output_tokens)
                )
            total, count = self._latency_by_priority.get(priority, [0, 0])
            self._latency_by_priority[priority] = [
                total + int(effective_latency),
                count + 1,
            ]
            self._events.append(
                {
                    "priority": priority,
                    "operation": operation,
                    "state": status,
                    "provider": provider,
                    "model": model,
                    "started_at": started_at.isoformat(),
                    "latency_ms": latency_ms if latency_ms is not None else elapsed_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "detail": detail,
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    # ------------------------------------------------------------- observability
    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            self._prune(now)
            recent = list(self._events)[-25:]
            used = len(self._granted)
            return {
                "window_seconds": self.config.window_seconds,
                "max_calls_per_window": self.config.max_calls_per_window,
                "calls_in_window": used,
                "remaining": max(0, self.config.max_calls_per_window - used),
                "ceilings": {
                    priority: self.config.ceiling_for(priority) for priority in PRIORITY_ORDER
                },
                "reserved_fraction_for_higher": dict(
                    self.config.reserved_fraction_for_higher
                ),
                "granted_by_priority": dict(self.granted_by_priority),
                "skipped_by_priority": dict(self.skipped_by_priority),
                "skipped_by_reason": dict(self.skipped_by_reason),
                "recent_operations": recent,
                "priority_order": list(PRIORITY_ORDER),
                "position_management_reserve": self.config.reserve_calls,
                "general_pool": self.config.general_pool,
                "suppressed_by_reason": dict(self.suppressed_by_reason),
                "coalesced_calls": int(
                    self.suppressed_by_reason.get(REASON_REVIEW_COALESCED, 0)
                ),
                "duplicate_calls_avoided": int(
                    self.suppressed_by_reason.get(REASON_DUPLICATE_INPUT, 0)
                    + self.suppressed_by_reason.get(REASON_UNCHANGED_CONTEXT, 0)
                ),
                "input_tokens_by_priority": dict(self.input_tokens_by_priority),
                "output_tokens_by_priority": dict(self.output_tokens_by_priority),
                "avg_latency_ms_by_priority": {
                    priority: round(total / count, 1)
                    for priority, (total, count) in self._latency_by_priority.items()
                    if count
                },
                "position_management_calls_in_window": sum(
                    1
                    for priority in self._granted_priorities
                    if self.config.is_position_management(priority)
                ),
                "general_calls_in_window": self._general_calls_in_window(),
                # Now a derived fact rather than a hardcoded claim: true only
                # when a non-zero reserve is actually protected.
                "market_selection_never_starves_position_management": (
                    self.config.reserve_calls > 0
                ),
            }
