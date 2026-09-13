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


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    window_seconds: float = 3600.0
    max_calls_per_window: int = 240
    reserved_fraction_for_higher: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_RESERVED_FRACTION_FOR_HIGHER)
    )

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


@dataclass(slots=True)
class BudgetTicket:
    """One granted call. Callers must call ``complete``/``fail`` in a finally."""

    granted: bool
    priority: str
    operation: str
    state: str
    started_at: datetime
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


@dataclass(slots=True)
class BudgetFallbackStats:
    """Observability counters for optional-research budget fallback.

    P3 exhaustion is not a decision failure: the Chief must still make the
    P1/P2 call with the canonical baseline factual context.  These counters
    distinguish that healthy degradation from true P1/P2 exhaustion.
    """

    p3_optional_fallback_count: int = 0
    p1_decisions_after_p3_skip: int = 0
    p2_decisions_after_p3_skip: int = 0
    last_research_budget_state: str | None = None
    last_research_fallback: str | None = None
    last_final_decision_priority: str | None = None
    last_final_decision_attempted: bool = False

    def snapshot(self) -> dict:
        return {
            "p3_optional_fallback_count": self.p3_optional_fallback_count,
            "p1_decisions_after_p3_skip": self.p1_decisions_after_p3_skip,
            "p2_decisions_after_p3_skip": self.p2_decisions_after_p3_skip,
            "last_research_budget_state": self.last_research_budget_state,
            "last_research_fallback": self.last_research_fallback,
            "last_final_decision_priority": self.last_final_decision_priority,
            "last_final_decision_attempted": self.last_final_decision_attempted,
        }


def classify_budget_pressure(snapshot: dict) -> dict[str, list[str] | str]:
    """Classify budget pressure without conflating P3 with core decisions.

    Watchdogs must never report ``GLOBAL_LLM_BUDGET_EXHAUSTED`` merely because
    the optional P3 research ceiling is exhausted.  Global exhaustion is a
    separate, stricter condition.
    """

    codes: list[str] = []
    if snapshot.get("global_budget_exhausted"):
        codes.append("D4_GLOBAL_LLM_BUDGET_EXHAUSTED")
    exhausted = snapshot.get("exhausted_by_priority") or {}
    if exhausted.get(P2_FINAL_ENTRY_DECISION):
        codes.append("D4_P2_FINAL_DECISION_BUDGET_EXHAUSTED")
    if exhausted.get(P1_POSITION_LIFECYCLE):
        codes.append("D4_P1_POSITION_BUDGET_EXHAUSTED")
    if exhausted.get(P3_SELECTED_SYMBOL_RESEARCH):
        codes.append("D4_P3_RESEARCH_BUDGET_EXHAUSTED")
    if not codes:
        verdict = "HEALTHY_BUDGET"
    elif all(code == "D4_P3_RESEARCH_BUDGET_EXHAUSTED" for code in codes):
        verdict = "OPTIONAL_RESEARCH_BUDGET_PRESSURE"
    else:
        verdict = "CORE_DECISION_BUDGET_PRESSURE"
    return {"verdict": verdict, "codes": codes}


class GlobalLLMBudget:
    """Rolling-window call budget with priority reservations."""

    def __init__(
        self,
        config: BudgetConfig | None = None,
        *,
        clock=None,
        growth_stage: str | None = None,
    ) -> None:
        self.config = config or BudgetConfig()
        self._clock = clock or time.monotonic
        self.growth_stage = growth_stage or "EXPLORATION"
        self._lock = threading.RLock()
        self._granted: deque[float] = deque()
        self._events: deque[dict] = deque(maxlen=500)
        self.skipped_by_priority: dict[str, int] = {}
        self.granted_by_priority: dict[str, int] = {}

    # ------------------------------------------------------------------ quota
    def _prune(self, now: float) -> None:
        cutoff = now - self.config.window_seconds
        while self._granted and self._granted[0] < cutoff:
            self._granted.popleft()

    def try_acquire(self, priority: str, *, operation: str) -> BudgetTicket:
        if priority not in PRIORITY_ORDER:
            raise ValueError(f"unknown LLM priority: {priority}")
        now = self._clock()
        with self._lock:
            self._prune(now)
            in_window = len(self._granted)
            ceiling = self.config.ceiling_for(priority)
            # Two independent guards:
            #   1. the global rolling-window maximum;
            #   2. the priority's reserved ceiling.
            #
            # P0/P1 safety and position management are exempt from guard 1:
            # lower-priority research must never consume the last window slot
            # and block an exit/reduction.  They remain bounded by their own
            # ceiling (guard 2).  P2+ honor the global maximum so a genuinely
            # exhausted window fails closed for new entries.
            safety_critical = priority in (
                P0_POSITION_SAFETY,
                P1_POSITION_LIFECYCLE,
            )
            already_granted = self.granted_by_priority.get(priority, 0)
            if safety_critical:
                # Safety/position management is bounded by its own ceiling,
                # not by total window usage.  Lower-priority research can
                # therefore never consume the last slot needed for an exit.
                blocked = already_granted >= ceiling
            else:
                blocked = (
                    in_window >= self.config.max_calls_per_window
                    or in_window >= ceiling
                )
            if blocked:
                self.skipped_by_priority[priority] = (
                    self.skipped_by_priority.get(priority, 0) + 1
                )
                ticket = BudgetTicket(
                    granted=False,
                    priority=priority,
                    operation=operation,
                    state=STATUS_SKIPPED_BUDGET,
                    started_at=datetime.now(UTC),
                )
                self._events.append(
                    {
                        "priority": priority,
                        "operation": operation,
                        "state": STATUS_SKIPPED_BUDGET,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
                return ticket
            self._granted.append(now)
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
        with self._lock:
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
            ceilings = {
                priority: self.config.ceiling_for(priority)
                for priority in PRIORITY_ORDER
            }
            # Reflect the actual admission rule above.  P0/P1 are capped by
            # their own priority count; P2+ are additionally capped by the
            # global rolling-window maximum.
            exhausted_by_priority = {
                priority: (
                    self.granted_by_priority.get(priority, 0) >= ceilings[priority]
                    if priority
                    in (P0_POSITION_SAFETY, P1_POSITION_LIFECYCLE)
                    else (
                        used >= self.config.max_calls_per_window
                        or used >= ceilings[priority]
                    )
                )
                for priority in PRIORITY_ORDER
            }
            return {
                "window_seconds": self.config.window_seconds,
                "max_calls_per_window": self.config.max_calls_per_window,
                "effective_stage": self.growth_stage,
                "effective_max_calls": self.config.max_calls_per_window,
                "calls_in_window": used,
                "remaining": max(0, self.config.max_calls_per_window - used),
                "global_budget_exhausted": used >= self.config.max_calls_per_window,
                "optional_research_budget_exhausted": exhausted_by_priority[
                    P3_SELECTED_SYMBOL_RESEARCH
                ],
                "core_decision_budget_exhausted": any(
                    exhausted_by_priority[p]
                    for p in (P1_POSITION_LIFECYCLE, P2_FINAL_ENTRY_DECISION)
                ),
                "exhausted_by_priority": exhausted_by_priority,
                "ceilings": ceilings,
                "reserved_fraction_for_higher": dict(
                    self.config.reserved_fraction_for_higher
                ),
                "granted_by_priority": dict(self.granted_by_priority),
                "skipped_by_priority": dict(self.skipped_by_priority),
                "recent_operations": recent,
                "priority_order": list(PRIORITY_ORDER),
                "market_selection_never_starves_position_management": True,
            }
