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
#: Research tiers get their own code so a spent P3/P4/P5 pool is never confused
#: with a spent entry pool or a spent position reserve.
REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED = (
    "SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED"
)
REASON_MARKET_SELECTION_BUDGET_EXHAUSTED = "MARKET_SELECTION_BUDGET_EXHAUSTED"
REASON_BACKGROUND_RESEARCH_BUDGET_EXHAUSTED = "BACKGROUND_RESEARCH_BUDGET_EXHAUSTED"
#: The whole rolling window (not just a pool) was spent.
REASON_GLOBAL_BUDGET_EXHAUSTED = "GLOBAL_BUDGET_EXHAUSTED"

#: Priority -> precise denial reason. Extends (never replaces) the existing
#: entry/position split so every pool is individually observable.
REASON_BY_PRIORITY: dict[str, str] = {
    P3_SELECTED_SYMBOL_RESEARCH: REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED,
    P4_MARKET_SELECTION: REASON_MARKET_SELECTION_BUDGET_EXHAUSTED,
    P5_BACKGROUND_RESEARCH: REASON_BACKGROUND_RESEARCH_BUDGET_EXHAUSTED,
}
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
    max_calls_per_window: int = 240
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

    def exhaustion_reason_for(self, priority: str, *, in_window: int | None = None) -> str:
        """Precise reason a priority was refused (see ``REASON_*``).

        ``in_window`` lets the caller distinguish a spent POOL from a fully spent
        WINDOW: when the whole rolling window is used up, no pool has capacity
        left and the honest answer is GLOBAL_LLM_BUDGET_EXHAUSTED.
        """
        # Position management is checked FIRST: the reserve bounds only
        # non-position work, so a position priority can legitimately consume the
        # whole window. When that happens the honest label is "position
        # management capacity spent", not the generic global code.
        if self.is_position_management(priority):
            return REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
        if in_window is not None and in_window >= self.max_calls_per_window:
            return REASON_GLOBAL_BUDGET_EXHAUSTED
        return REASON_BY_PRIORITY.get(priority, REASON_ENTRY_BUDGET_EXHAUSTED)



@dataclass(frozen=True, slots=True)
class BudgetDenial:
    """Structured, entity-complete refusal for one budget request.

    Replaces the bare ``"SKIPPED_BUDGET"`` string that the tool-selection path
    used to return: that string forced every consumer (tool orchestrator,
    decision trace, supervisor) to treat a spent research pool, a spent entry
    pool and a spent position reserve as the same opaque event.
    """

    reason: str
    priority: str
    operation: str
    pool: str
    effective_ceiling: int
    current_usage: int
    total_limit: int

    @classmethod
    def from_ticket(cls, ticket: BudgetTicket) -> BudgetDenial:
        return cls(
            reason=str(ticket.reason or STATUS_SKIPPED_BUDGET),
            priority=ticket.priority,
            operation=ticket.operation,
            pool=("POSITION_MANAGEMENT"
                  if ticket.priority in POSITION_MANAGEMENT_PRIORITIES
                  else "GENERAL"),
            effective_ceiling=int(ticket.effective_ceiling or 0),
            current_usage=int(ticket.current_usage or 0),
            total_limit=int(ticket.total_limit or 0),
        )

    def as_reason_code(self) -> str:
        return self.reason

    def as_facts(self) -> dict:
        return {
            "reason": self.reason,
            "priority": self.priority,
            "operation": self.operation,
            "budget_pool": self.pool,
            "effective_ceiling": self.effective_ceiling,
            "current_usage": self.current_usage,
            "total_limit": self.total_limit,
        }


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
    #: Diagnostics captured at decision time so a denial is self-explaining.
    effective_ceiling: int | None = None
    current_usage: int | None = None
    total_limit: int | None = None
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
        token_usage: dict | None = None,
    ) -> None:
        if self._budget is not None and not self._completed:
            if token_usage is not None:
                self._budget.record_prompt_cache_usage(self.operation, token_usage)
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
        # Provider prompt-cache accounting (observability only).
        self._cache_hit_tokens = 0
        self._cache_miss_tokens = 0
        self._cache_known_calls = 0
        self._cache_unknown_calls = 0
        self._cache_by_operation: dict[str, dict[str, int]] = {}

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

    def _refuse(
        self, priority: str, operation: str, *, in_window: int | None = None
    ) -> BudgetTicket:
        """Record and return a refused ticket carrying the precise reason."""
        reason = self.config.exhaustion_reason_for(priority, in_window=in_window)
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
            effective_ceiling=self.config.ceiling_for(priority),
            current_usage=(
                in_window
                if in_window is not None
                else len(self._granted)
            ),
            total_limit=self.config.max_calls_per_window,
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
                return self._refuse(priority, operation, in_window=in_window)
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
                if in_window >= effective:
                    return self._refuse(
                        priority, operation, in_window=in_window
                    )
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

    def record_prompt_cache_usage(self, operation: str, usage: dict | None) -> None:
        """Record provider prompt-cache facts without coercing UNKNOWN to 0."""
        raw = usage or {}
        hit = raw.get("prompt_cache_hit_tokens")
        miss = raw.get("prompt_cache_miss_tokens")
        try:
            hit_i = int(hit) if hit is not None and not isinstance(hit, bool) else None
            miss_i = (
                int(miss)
                if miss is not None and not isinstance(miss, bool)
                else None
            )
        except (TypeError, ValueError):
            hit_i = miss_i = None
        op = self._cache_by_operation.setdefault(
            operation,
            {"hit_tokens": 0, "miss_tokens": 0, "known_calls": 0, "unknown_calls": 0},
        )
        if hit_i is None or miss_i is None:
            self._cache_unknown_calls += 1
            op["unknown_calls"] += 1
            return
        self._cache_hit_tokens += hit_i
        self._cache_miss_tokens += miss_i
        self._cache_known_calls += 1
        op["hit_tokens"] += hit_i
        op["miss_tokens"] += miss_i
        op["known_calls"] += 1

    def prompt_cache_metrics(self) -> dict:
        hit = self._cache_hit_tokens
        miss = self._cache_miss_tokens
        total = hit + miss
        rate = (hit / total) if total > 0 else None
        operations: dict[str, dict] = {}
        for operation, values in self._cache_by_operation.items():
            op_hit = int(values.get("hit_tokens", 0))
            op_miss = int(values.get("miss_tokens", 0))
            op_total = op_hit + op_miss
            operations[operation] = {
                "status": "KNOWN" if op_total > 0 else "UNKNOWN",
                "hit_tokens": op_hit if values.get("known_calls") else None,
                "miss_tokens": op_miss if values.get("known_calls") else None,
                "eligible_prompt_tokens": op_total if values.get("known_calls") else None,
                "hit_rate": (op_hit / op_total) if op_total > 0 else None,
                "known_calls": int(values.get("known_calls", 0)),
                "unknown_calls": int(values.get("unknown_calls", 0)),
            }
        return {
            "status": "KNOWN" if total > 0 else "UNKNOWN",
            "hit_tokens": hit if self._cache_known_calls else None,
            "miss_tokens": miss if self._cache_known_calls else None,
            "eligible_prompt_tokens": total if self._cache_known_calls else None,
            "hit_rate": rate,
            "known_calls": self._cache_known_calls,
            "unknown_calls": self._cache_unknown_calls,
            "operations": operations,
        }

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
            # Reflect the actual admission rule above.  Position-management
            # priorities are bounded by their own ceiling; general work is also
            # bounded by the protected reserve (``general_pool``).
            exhausted_by_priority = {}
            for priority in PRIORITY_ORDER:
                effective = ceilings[priority]
                if (
                    not self.config.is_position_management(priority)
                    and self.config.reserve_calls > 0
                ):
                    effective = min(effective, self.config.general_pool)
                exhausted_by_priority[priority] = used >= effective
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
                "prompt_cache": self.prompt_cache_metrics(),
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
